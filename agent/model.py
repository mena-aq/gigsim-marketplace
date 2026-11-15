"""Structured local inference with per-node routes and measured token usage."""

import os

import httpx
from pydantic import BaseModel

from agent.config import ROOT
from mcp_servers.common.errors import ToolFailure


class NodeModel:
    def __init__(self, config: dict, *, transport=None):
        self.config = config
        self.transport = transport

    async def ask(
        self, role: str, payload: dict, schema: type[BaseModel]
    ) -> tuple[BaseModel, int]:
        import json

        settings = self.config["orchestration"]
        profile = self.config["profiles"][os.getenv("MODEL_PROFILE", "open")]
        prompt = (ROOT / "agent/prompts" / f"{role}.md").read_text()
        content = json.dumps(payload, ensure_ascii=False)
        if len(content) > settings["max_input_characters"]:
            raise ToolFailure(
                "context_budget_exceeded", "Node input exceeds context budget"
            )
        usage = 0
        failure = ToolFailure("model_failed", "Node model is unavailable", True)
        models = [profile[role]]
        if role in settings["cheap_nodes"] and profile.get("fallback"):
            models.append(profile["fallback"])
        for model in dict.fromkeys(models):
            try:
                async with httpx.AsyncClient(
                    timeout=settings["model_timeout_seconds"], transport=self.transport
                ) as client:
                    response = await client.post(
                        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
                        + "/api/chat",
                        json={
                            "model": model,
                            "stream": False,
                            "format": schema.model_json_schema(),
                            "messages": [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": content},
                            ],
                            "options": {
                                "temperature": 0,
                                "seed": 0,
                                "num_ctx": settings["context_tokens"],
                                "num_predict": settings.get(
                                    "output_tokens_by_role", {}
                                ).get(role, settings["output_tokens"]),
                                "num_thread": self.config["rag"]["cpu_threads"],
                            },
                        },
                    )
                    response.raise_for_status()
                data = response.json()
                usage += data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                if data.get("done_reason") == "length":
                    failure = ToolFailure(
                        "model_output_truncated",
                        "Structured output exceeded the model output-token limit; shorten the node response",
                    )
                    continue
                return schema.model_validate_json(data["message"]["content"]), usage
            except httpx.TimeoutException:
                failure = ToolFailure(
                    "model_timeout",
                    "Local model timed out; the CPU may be processing other requests",
                    True,
                )
            except httpx.HTTPError:
                failure = ToolFailure(
                    "model_unavailable", "Local model request failed", True
                )
            except (ValueError, KeyError):
                failure = ToolFailure(
                    "model_response_invalid",
                    "Local model response did not match the required schema",
                )
        raise failure
