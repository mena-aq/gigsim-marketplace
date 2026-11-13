"""Validated model and retrieval choices; runtime addresses come from environment."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, model_validator

Variant = Literal["v0", "v1", "v2", "v3", "v8"]
VARIANTS = ("v0", "v1", "v2", "v3", "v8")
ROOT = Path(__file__).resolve().parents[1]


class RagConfig(BaseModel):
    active_variant: Variant = "v0"
    chunk_tokens: int = Field(default=200, ge=10, le=500)
    overlap_tokens: int = Field(default=40, ge=0)
    candidate_k: int = Field(default=20, ge=10, le=100)
    rrf_constant: int = Field(default=60, ge=1)
    embedding_dimensions: int = 384
    embedding_context_tokens: int = 512
    tokenizer_model: str
    tokenizer_revision: str
    reranker_revision: str
    reranker_file: str = "onnx/model.onnx"
    llm_model: str
    llm_context_tokens: int = 8192
    llm_output_tokens: int = 768
    llm_timeout_seconds: float = 180
    llm_budget_seconds: float = Field(default=240, gt=0)
    max_requirements: int = 6
    grade_candidates: int = 5
    cpu_threads: int = 2
    embeddings_model: str
    reranker_model: str
    ollama_url: str = "http://localhost:11434"
    chroma_url: str = "http://localhost:8001"
    data_dir: Path = Path("data/processed/rag")

    @model_validator(mode="after")
    def valid_chunking(self):
        if (
            self.overlap_tokens >= self.chunk_tokens
            or self.chunk_tokens + 2 > self.embedding_context_tokens
        ):
            raise ValueError("Chunk/overlap settings exceed the embedding context")
        return self

    def index_fingerprint(self, digest: str) -> str:
        settings = {
            key: getattr(self, key)
            for key in (
                "chunk_tokens",
                "overlap_tokens",
                "embedding_dimensions",
                "tokenizer_revision",
                "embeddings_model",
            )
        }
        settings.update(model_digest=digest, format_version=1)
        return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def load_config(path: Path | None = None) -> RagConfig:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    raw = yaml.safe_load((path or ROOT / "agent/config.yaml").read_text())
    return RagConfig(
        **raw["rag"],
        embeddings_model=raw["models"]["embeddings"],
        reranker_model=raw["models"]["reranker"],
        ollama_url=env.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        chroma_url=env.get(
            "CHROMA_URL",
            f"http://{env.get('CHROMA_HOST', 'localhost')}:{env.get('CHROMA_PORT', '8001')}",
        ),
        data_dir=Path(env.get("RAG_DATA_DIR", str(ROOT / "data/processed/rag"))),
    )
