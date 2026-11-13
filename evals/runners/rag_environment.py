"""Capture runtime provenance separately from measured quality/latency observations."""

import hashlib
import importlib.metadata
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import httpx

from rag.config import ROOT, RagConfig


async def capture_environment(config: RagConfig, path: Path, fingerprint: str) -> None:
    existing = json.loads(path.read_text()) if path.is_file() else None
    async with httpx.AsyncClient(timeout=10) as client:
        tags = await client.get(config.ollama_url + "/api/tags")
        tags.raise_for_status()
        version = await client.get(config.ollama_url + "/api/version")
        version.raise_for_status()
    names = {config.embeddings_model, config.llm_model}
    models = {
        item["name"]: {"digest": item["digest"], "details": item.get("details", {})}
        for item in tags.json()["models"]
        if item["name"] in names
    }
    if set(models) != names:
        raise RuntimeError("Configured local models are not installed")
    packages = ("onnxruntime", "tokenizers", "numpy", "pypdf", "langgraph", "httpx")
    record = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "observation_fingerprint": fingerprint,
        "ollama_version": version.json()["version"],
        "models": models,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in packages},
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "measurement_environment": "Shared development CPU; no dedicated-hardware isolation",
    }
    if existing is not None:
        for key in (
            "observation_fingerprint",
            "ollama_version",
            "models",
            "python",
            "packages",
            "uv_lock_sha256",
        ):
            if existing.get(key) != record[key]:
                raise RuntimeError(
                    "Cannot resume: the recorded model/runtime environment changed"
                )
        return
    path.write_text(json.dumps(record, indent=2) + "\n")
