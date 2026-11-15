"""Retriever factory and user-scoped model/index context."""

import time

from rag.config import RagConfig
from rag.index.chroma import Chroma
from rag.ingest.chunks import Chunker
from rag.ingest.pipeline import read_manifest, validate_sources
from rag.llm import StructuredLLM
from rag.models import Embeddings, Reranker
from rag.ranking import unique_items
from rag.types import Chunk, Hit, RagFailure, Retrieval
from rag.variants import v0_naive, v1_decomposed, v2_hybrid, v3_reranked, v8_corrective

RETRIEVERS = {
    "v0": v0_naive.retrieve,
    "v1": v1_decomposed.retrieve,
    "v2": v2_hybrid.retrieve,
    "v3": v3_reranked.retrieve,
    "v8": v8_corrective.retrieve,
}


def get_retriever(variant: str):
    if variant not in RETRIEVERS:
        raise ValueError("Unknown RAG variant")
    return RETRIEVERS[variant]


class Pipeline:
    def __init__(
        self,
        config: RagConfig,
        root,
        user_id: str,
        persona: str,
        *,
        embeddings=None,
        chroma=None,
        chunker=None,
        llm=None,
        reranker=None,
    ):
        self.config, self.root, self.user_id, self.persona = (
            config,
            root,
            user_id,
            persona,
        )
        self.embeddings = embeddings or Embeddings(config)
        self.chroma = chroma or Chroma(config.chroma_url)
        self.chunker = chunker
        self.llm = llm or StructuredLLM(config)
        self.reranker = reranker
        self.diagnostics = {}
        self.filtered_chunks = []
        self.filters = {}
        self.retired: frozenset[str] = frozenset()
        self.retired_chunk_ids: set[str] = set()

    async def prepare(self, filters: dict | None = None) -> None:
        self.manifest = read_manifest(self.config, self.user_id)
        if self.manifest["persona"] != self.persona:
            raise RagFailure("forbidden", "Index persona mismatch")
        digest = await self.embeddings.digest()
        if self.manifest["fingerprint"] != self.config.index_fingerprint(digest):
            raise RagFailure(
                "index_incompatible",
                "Embedding model or chunk settings changed; re-ingest",
            )
        validate_sources(self.manifest, self.root, self.persona)
        self.chunker = self.chunker or Chunker(
            self.config.data_dir / "models/embedding/tokenizer.json",
            self.config.chunk_tokens,
            self.config.overlap_tokens,
            self.config.tokenizer_revision,
        )
        self.filters = {
            key: value for key, value in (filters or {}).items() if value is not None
        }
        everything = {
            record["chunk"]["chunk_id"]: Chunk.model_validate(record["chunk"])
            for record in self.manifest["records"]
        }
        # Retired (user-deleted) evidence is invisible: it cannot be retrieved, and any
        # stale reference to it fails verification instead of silently supporting a claim.
        self.retired_chunk_ids = {
            key for key, chunk in everything.items() if chunk.id in self.retired
        }
        self.chunks = {
            key: chunk
            for key, chunk in everything.items()
            if key not in self.retired_chunk_ids
        }
        self.filtered_chunks = [
            chunk
            for chunk in self.chunks.values()
            if all(getattr(chunk, key) == value for key, value in self.filters.items())
        ]

    async def dense(self, query: str, k: int) -> list[Hit]:
        if not self.filtered_chunks:
            return []
        text, truncated = self.chunker.truncate(
            query, self.config.embedding_context_tokens - 2
        )
        self.diagnostics["query_truncated"] = (
            self.diagnostics.get("query_truncated", False) or truncated
        )
        vector = (await self.embeddings.embed([text]))[0]
        results = await self.chroma.query(
            self.manifest["collection"],
            self.user_id,
            vector,
            min(k, len(self.filtered_chunks)) + len(self.retired_chunk_ids),
            self.filters,
        )
        results = [
            (key, score) for key, score in results if key not in self.retired_chunk_ids
        ][:k]
        allowed = {chunk.chunk_id for chunk in self.filtered_chunks}
        if any(key not in allowed for key, _ in results):
            raise RagFailure(
                "index_incompatible",
                "Vector index returned an unexpected chunk; re-ingest",
            )
        return [Hit(chunk=self.chunks[key], score=score) for key, score in results]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        self.reranker = self.reranker or Reranker(self.config)
        return self.reranker.score(query, texts)

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict | None = None,
        variant: str | None = None,
    ) -> Retrieval:
        # A new context per request avoids mutable filter/diagnostic races.
        self.diagnostics = {}
        await self.prepare(filters)
        before = len(self.llm.usage)
        start = time.perf_counter()
        selected = variant or self.config.active_variant
        hits = await get_retriever(selected)(
            query, self, max(self.config.candidate_k, k)
        )
        hits = unique_items(hits, k)
        status = (
            "empty"
            if not hits
            else "partial"
            if self.diagnostics.get("grade") == "weak"
            else "complete"
        )
        self.diagnostics.update(
            seconds=time.perf_counter() - start, llm_usage=self.llm.usage[before:]
        )
        return Retrieval(
            hits=hits, variant=selected, status=status, diagnostics=self.diagnostics
        )

    async def evidence(self, chunk_ids: list[str]) -> list[Chunk]:
        await self.prepare()
        if any(key not in self.chunks for key in chunk_ids):
            raise RagFailure(
                "evidence_unavailable",
                "A reference is stale or belongs to another user",
            )
        return [self.chunks[key] for key in dict.fromkeys(chunk_ids)]
