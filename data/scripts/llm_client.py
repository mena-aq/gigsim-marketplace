"""Provider-agnostic LLM helper for Phase 0 data generation.

Provider order with DATA_LLM_PROVIDER=auto (the default):
  ollama (local) -> groq (if GROQ_API_KEY set) -> none (callers use canned fallbacks)

Pin a provider with DATA_LLM_PROVIDER=ollama, =groq or =none.

Groq calls are quota-aware: the helper reads x-ratelimit-* and Retry-After
headers, paces calls so a batch never trips 8K TPM, and raises QuotaExhausted
(not a generic error) when the daily cap or LLM_TOKEN_BUDGET is reached.

Environment:
  OLLAMA_BASE_URL       default http://localhost:11434
  OLLAMA_MODEL          default qwen2.5:3b
  GROQ_API_KEY / GROQ_MODEL (default openai/gpt-oss-120b)
  GROQ_REASONING_EFFORT default low (reasoning tokens count against the quota)
  LLM_TIMEOUT_SECONDS   default 300 (CPU inference is slow)
  LLM_TOKEN_BUDGET      optional per-run prompt+completion token cap
  LLM_MIN_INTERVAL_SECONDS  optional floor between calls (default 0)
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class QuotaExhausted(RuntimeError):
    """Daily provider quota or the local per-run token budget was reached."""


class _RateLimited(Exception):
    def __init__(self, wait: float, daily: bool, message: str) -> None:
        super().__init__(message)
        self.wait = wait
        self.daily = daily


_provider_cache: str | None = None
_next_call_at = 0.0
_groq_reasoning_supported = True
_usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}


def load_env_file() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def groq_model() -> str:
    return os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)


def token_budget() -> int | None:
    raw = os.environ.get("LLM_TOKEN_BUDGET", "").strip()
    return int(raw) if raw else None


def usage() -> dict:
    total = _usage["prompt_tokens"] + _usage["completion_tokens"]
    return {**_usage, "total_tokens": total, "budget": token_budget()}


def usage_summary() -> str:
    current = usage()
    text = (f"{current['requests']} requests, {current['total_tokens']} tokens "
            f"({current['prompt_tokens']} in / {current['completion_tokens']} out)")
    if current["budget"]:
        text += f" of {current['budget']} budget"
    return text


def reset_usage() -> None:
    for key in _usage:
        _usage[key] = 0


def ollama_available() -> bool:
    try:
        response = httpx.get(f"{ollama_base_url()}/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


def provider(force: bool = False) -> str:
    """Return the active provider: ollama, groq or none."""
    global _provider_cache
    if _provider_cache is not None and not force:
        return _provider_cache
    load_env_file()
    choice = os.environ.get("DATA_LLM_PROVIDER", "auto").strip().lower()
    if choice in {"ollama", "groq", "none"}:
        _provider_cache = choice
    elif ollama_available():
        _provider_cache = "ollama"
    elif os.environ.get("GROQ_API_KEY", "").strip():
        _provider_cache = "groq"
    else:
        _provider_cache = "none"
    return _provider_cache


def describe() -> str:
    selected = provider()
    if selected == "ollama":
        return f"ollama ({ollama_model()} @ {ollama_base_url()})"
    if selected == "groq":
        return f"groq ({groq_model()})"
    return "none (canned fallbacks)"


def parse_duration(value: str | None) -> float:
    """Parse '7.66s', '2m59.56s', '300ms', '60' (seconds) into seconds."""
    if not value:
        return 0.0
    text = str(value).strip().lower()
    if not text:
        return 0.0
    if text.replace(".", "", 1).isdigit():
        return float(text)
    if text.endswith("ms"):
        match = re.match(r"([\d.]+)", text)
        return float(match.group(1)) / 1000 if match else 0.0
    total = 0.0
    for amount, unit in re.findall(r"([\d.]+)\s*(h|m|s)", text):
        total += float(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def _record_usage(prompt_tokens: int, completion_tokens: int) -> None:
    _usage["requests"] += 1
    _usage["prompt_tokens"] += int(prompt_tokens or 0)
    _usage["completion_tokens"] += int(completion_tokens or 0)


def _enforce_budget(estimated_next: int) -> None:
    budget = token_budget()
    used = _usage["prompt_tokens"] + _usage["completion_tokens"]
    if budget is not None and used + estimated_next > budget:
        raise QuotaExhausted(
            f"token budget reached ({used}/{budget} used, next call needs ~{estimated_next}); "
            "rerun later with a higher LLM_TOKEN_BUDGET to continue"
        )


def _wait_for_pacing() -> None:
    wait = _next_call_at - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def _note_groq_limits(headers: httpx.Headers, estimated_next: int) -> None:
    global _next_call_at
    now = time.monotonic()
    min_interval = float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", "0") or 0)
    _next_call_at = max(_next_call_at, now + min_interval)
    try:
        remaining = int(headers.get("x-ratelimit-remaining-tokens", ""))
    except (TypeError, ValueError):
        remaining = None
    reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
    if remaining is not None and remaining < estimated_next and reset > 0:
        _next_call_at = max(_next_call_at, now + reset + 0.5)


def _rate_limited(response: httpx.Response) -> _RateLimited:
    headers = response.headers
    wait = parse_duration(headers.get("retry-after"))
    if not wait:
        wait = parse_duration(headers.get("x-ratelimit-reset-tokens"))
    if not wait:
        wait = parse_duration(headers.get("x-ratelimit-reset-requests"))
    wait = min(max(wait or 30.0, 1.0), 180.0)
    body = response.text.lower()
    daily = any(phrase in body for phrase in (
        "tokens per day", "requests per day", "per day (tpd)", "per day (rpd)",
        "daily limit", "tpd:", "rpd:",
    ))
    return _RateLimited(wait, daily, response.text[:300])


def _chat_ollama(prompt: str, max_tokens: int, temperature: float) -> str:
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))
    payload = {
        "model": ollama_model(),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{ollama_base_url()}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    _record_usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
    content = (data.get("message") or {}).get("content", "").strip()
    if not content:
        raise RuntimeError("empty response from Ollama")
    return content


def _post_groq(prompt: str, max_tokens: int, temperature: float) -> httpx.Response:
    global _groq_reasoning_supported
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    payload = {
        "model": groq_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    effort = os.environ.get("GROQ_REASONING_EFFORT", "low").strip()
    if effort and _groq_reasoning_supported:
        payload["reasoning_effort"] = effort
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        if (response.status_code == 400 and effort
                and "reasoning_effort" in response.text.lower()):
            _groq_reasoning_supported = False
            payload.pop("reasoning_effort", None)
            response = client.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
    return response


def _chat_groq(prompt: str, max_tokens: int, temperature: float) -> str:
    response = _post_groq(prompt, max_tokens, temperature)
    if response.status_code == 429:
        raise _rate_limited(response)
    if response.status_code == 413:
        raise RuntimeError(
            "Groq rejected the request as too large for the 8K TPM free tier; "
            "lower the batch size or max tokens"
        )
    response.raise_for_status()
    data = response.json()
    usage_data = data.get("usage") or {}
    _record_usage(usage_data.get("prompt_tokens", 0), usage_data.get("completion_tokens", 0))
    _note_groq_limits(response.headers, max_tokens + 700)
    content = (data["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError("empty response from Groq")
    return content


def chat(prompt: str, max_tokens: int = 800, temperature: float = 0.8,
         retries: int = 4) -> str | None:
    """Send one prompt and return the text response, or None if no provider."""
    selected = provider()
    if selected == "none":
        return None
    estimated_next = max_tokens + 1200
    last_error: Exception | None = None
    for attempt in range(retries):
        _enforce_budget(estimated_next)
        _wait_for_pacing()
        try:
            if selected == "ollama":
                return _chat_ollama(prompt, max_tokens, temperature)
            return _chat_groq(prompt, max_tokens, temperature)
        except QuotaExhausted:
            raise
        except _RateLimited as exc:
            if exc.daily:
                raise QuotaExhausted(
                    f"{selected} daily quota exhausted; rerun later to resume. {exc}"
                ) from exc
            print(f"[llm] {selected} rate limited, waiting {exc.wait:.0f}s")
            time.sleep(exc.wait)
        except Exception as exc:  # noqa: BLE001 - retry transient failures
            last_error = exc
            wait = min(2 ** (attempt + 1), 20)
            print(f"[llm] {selected} call failed ({exc}), retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last_error}")


def parse_json_object(content: str) -> dict:
    """Extract a JSON object from LLM output, tolerating fences and prose."""
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
