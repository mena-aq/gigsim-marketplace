"""Explicit incremental ingestion and atomic publication of tenant index manifests."""

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select

from apps.api.models import MCPCredential, User
from mcp_servers.common.runtime import Runtime
from rag.config import RagConfig, load_config
from rag.index.chroma import Chroma
from rag.ingest.chunks import Chunker
from rag.ingest.loaders import load_documents, source_hash
from rag.models import Embeddings
from rag.types import RagFailure


def manifest_path(config: RagConfig, user_id: str) -> Path:
    return (
        config.data_dir
        / "indexes"
        / (hashlib.sha256(user_id.encode()).hexdigest() + ".json")
    )


def read_manifest(config: RagConfig, user_id: str) -> dict:
    path = manifest_path(config, user_id)
    if not path.is_file():
        raise RagFailure("index_missing", "No index for this user; run make rag-ingest")
    data = json.loads(path.read_text())
    if data.get("user_id") != user_id:
        raise RagFailure("forbidden", "Index namespace mismatch")
    return data


def validate_sources(manifest: dict, root: Path, persona: str) -> None:
    directory = (root / persona).resolve()
    if directory.parent != root.resolve() or not directory.is_dir():
        raise RagFailure(
            "index_stale", "Assigned corpus directory changed or is missing"
        )
    for relative, digest in manifest["sources"].items():
        path = directory / relative
        if (
            not path.resolve().is_relative_to(directory)
            or not path.is_file()
            or source_hash(path) != digest
        ):
            raise RagFailure(
                "index_stale",
                "Evidence changed or was deleted; re-ingest before retrieval",
            )


async def ingest(
    config: RagConfig,
    root: Path,
    user_id: str,
    persona: str,
    *,
    embeddings=None,
    chroma=None,
    chunker=None,
) -> dict:
    path = manifest_path(config, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prevent two operator processes publishing competing index manifests.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        embeddings = embeddings or Embeddings(config)
        chroma = chroma or Chroma(config.chroma_url)
        chunker = chunker or Chunker(
            config.data_dir / "models/embedding/tokenizer.json",
            config.chunk_tokens,
            config.overlap_tokens,
            config.tokenizer_revision,
        )
        digest = await embeddings.digest()
        fingerprint = config.index_fingerprint(digest)
        old = json.loads(path.read_text()) if path.is_file() else {}
        reusable = (
            {record["chunk"]["chunk_id"]: record for record in old.get("records", [])}
            if old.get("fingerprint") == fingerprint
            else {}
        )
        documents = load_documents(root, persona)
        chunks = [
            chunk
            for document in documents
            for chunk in chunker.split(document, user_id)
        ]
        if not chunks:
            raise RagFailure("corpus_unavailable", "The corpus has no indexable text")
        missing = [chunk for chunk in chunks if chunk.chunk_id not in reusable]
        vectors = (
            await embeddings.embed([chunk.text for chunk in missing]) if missing else []
        )
        fresh = {
            chunk.chunk_id: {"chunk": chunk.model_dump(), "embedding": vector}
            for chunk, vector in zip(missing, vectors, strict=True)
        }
        records = [
            reusable.get(chunk.chunk_id) or fresh[chunk.chunk_id] for chunk in chunks
        ]
        collection = await chroma.collection(
            "gigbid-"
            + hashlib.sha256((user_id + fingerprint).encode()).hexdigest()[:40]
        )
        await chroma.upsert(collection, user_id, records)
        current = {chunk.chunk_id for chunk in chunks}
        deleted = [key for key in reusable if key not in current]
        await chroma.delete(collection, user_id, deleted)
        manifest = {
            "version": 1,
            "user_id": user_id,
            "persona": persona,
            "fingerprint": fingerprint,
            "embedding_digest": digest,
            "collection": collection,
            "sources": {
                document.source: document.source_hash for document in documents
            },
            "records": records,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False))
        os.replace(temporary, path)
    return {
        "persona": persona,
        "documents": len(documents),
        "chunks": len(chunks),
        "embedded": len(missing),
        "reused": len(chunks) - len(missing),
        "deleted": len(deleted),
    }


async def main() -> None:
    config = load_config()
    runtime = Runtime()
    try:
        async with runtime.sessions() as session:
            users = (
                (
                    await session.execute(
                        select(User).join(
                            MCPCredential, MCPCredential.user_id == User.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not users:
            raise SystemExit("Run make mcp-bootstrap before ingestion")
        for user in users:
            print(
                json.dumps(
                    await ingest(
                        config, runtime.settings.mcp_persona_dir, user.id, user.persona
                    )
                )
            )
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
