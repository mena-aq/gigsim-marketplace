"""Offset-preserving WordPiece chunks compatible with MiniLM embeddings."""

import hashlib
import json
from pathlib import Path

from tokenizers import Tokenizer

from rag.types import Chunk, Document, RagFailure


class Chunker:
    def __init__(
        self,
        tokenizer_path: Path,
        size: int = 200,
        overlap: int = 40,
        expected_revision: str | None = None,
    ):
        if not tokenizer_path.is_file():
            raise RagFailure(
                "model_unavailable",
                "Run make rag-models to install the embedding tokenizer",
            )
        if expected_revision is not None:
            manifest_path = tokenizer_path.parent.parent / "manifest.json"
            installed = (
                json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            )
            if installed.get("tokenizer_revision") != expected_revision:
                raise RagFailure(
                    "model_unavailable",
                    "Embedding tokenizer revision changed; run make rag-models",
                )
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.size, self.overlap = size, overlap

    def split(self, document: Document, user_id: str) -> list[Chunk]:
        encoded = self.tokenizer.encode(document.text, add_special_tokens=False)
        chunks = []
        for offset in range(0, len(encoded.ids), self.size - self.overlap):
            group = encoded.offsets[offset : offset + self.size]
            if not group:
                break
            start, end = group[0][0], group[-1][1]
            chunk_id = hashlib.sha256(
                f"{user_id}:{document.id}:{document.source_hash}:{start}:{end}".encode()
            ).hexdigest()
            chunks.append(
                Chunk(
                    **{**document.model_dump(), "text": document.text[start:end]},
                    chunk_id=chunk_id,
                    start=start,
                    end=end,
                )
            )
            if offset + self.size >= len(encoded.ids):
                break
        return chunks

    def truncate(self, text: str, limit: int) -> tuple[str, bool]:
        encoded = self.tokenizer.encode(text, add_special_tokens=False)
        if len(encoded.ids) <= limit:
            return text, False
        return text[: encoded.offsets[limit - 1][1]], True
