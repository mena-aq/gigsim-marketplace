"""Bounded structured Qwen inference. Instructions live only in prompt files."""

import asyncio
import time

import httpx
from pydantic import BaseModel, ValidationError

from rag.config import ROOT, RagConfig
from rag.types import RagFailure


class StructuredLLM:
    def __init__(self, config: RagConfig):
        self.config = config
        self.usage = []
        self.lock = asyncio.Lock()
        self.deadline = None

    async def ask(self, prompt: str, payload: dict, schema: type[BaseModel]):
        import json

        instructions = (ROOT / "agent/prompts" / (prompt + ".md")).read_text()
        content = json.dumps(payload, ensure_ascii=False)
        # Reject oversized inputs explicitly; do not silently lose instructions.
        if len(content) > 24000:
            raise RagFailure(
                "context_budget_exceeded",
                "Structured model input exceeds the configured safe text budget",
            )
        async with self.lock:
            for attempt in range(2):
                start = time.perf_counter()
                self.deadline = self.deadline or start + self.config.llm_budget_seconds
                remaining = self.deadline - start
                if remaining <= 0:
                    raise RagFailure(
                        "model_budget_exceeded",
                        "The per-request local-model time budget was exhausted",
                        True,
                    )
                try:
                    async with httpx.AsyncClient(
                        timeout=min(self.config.llm_timeout_seconds, remaining)
                    ) as client:
                        response = await client.post(
                            self.config.ollama_url + "/api/chat",
                            json={
                                "model": self.config.llm_model,
                                "stream": False,
                                "format": schema.model_json_schema(),
                                "messages": [
                                    {"role": "system", "content": instructions},
                                    {"role": "user", "content": content},
                                ],
                                "options": {
                                    "temperature": 0,
                                    "seed": 0,
                                    "num_ctx": self.config.llm_context_tokens,
                                    "num_predict": self.config.llm_output_tokens,
                                    "num_thread": self.config.cpu_threads,
                                },
                                "keep_alive": "5m",
                            },
                        )
                        response.raise_for_status()
                    data = response.json()
                    self.usage.append(
                        {
                            "prompt": prompt,
                            "seconds": time.perf_counter() - start,
                            "prompt_tokens": data.get("prompt_eval_count", 0),
                            "completion_tokens": data.get("eval_count", 0),
                            "evaluation_seconds": data.get("eval_duration", 0) / 1e9,
                        }
                    )
                    return schema.model_validate_json(data["message"]["content"])
                except (httpx.HTTPError, KeyError, ValueError, ValidationError):
                    if attempt == 1:
                        raise RagFailure(
                            "model_response_invalid",
                            "Structured Qwen inference failed; no result was guessed",
                            True,
                        ) from None
                    await asyncio.sleep(0.25)
        raise RagFailure("model_response_invalid", "Structured inference failed", True)
