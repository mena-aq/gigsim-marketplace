"""Local-only source loaders. No scraping, repo API calls, or generated metadata."""

import hashlib
from pathlib import Path

import yaml
from pypdf import PdfReader

from rag.types import Document, RagFailure

CODE = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sql",
    ".java",
    ".go",
    ".rs",
    ".sh",
    ".yaml",
    ".yml",
}


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_documents(root: Path, persona: str) -> list[Document]:
    directory = (root / persona).resolve()
    if directory.parent != root.resolve() or not directory.is_dir():
        raise RagFailure("corpus_unavailable", "Assigned persona corpus is missing")
    documents = []
    for path in sorted(directory.rglob("*")):
        if (
            path.suffix.lower() not in CODE | {".md", ".txt", ".pdf"}
            or not path.is_file()
        ):
            continue
        if not path.resolve().is_relative_to(directory):
            raise RagFailure(
                "invalid_source", "A corpus symlink escapes its assigned directory"
            )
        if path.stat().st_size > 2_000_000:
            raise RagFailure(
                "invalid_source", "A source exceeds the 2 MB local ingestion limit"
            )
        if path.suffix.lower() == ".pdf":
            text = "\n".join(
                page.extract_text() or "" for page in PdfReader(path).pages
            )
            if not text.strip():
                raise RagFailure(
                    "invalid_source",
                    "A PDF has no extractable text; OCR is not included",
                )
        else:
            text = path.read_text(encoding="utf-8")
        meta = {}
        if text.startswith("---\n"):
            parts = text.split("---", 2)
            if len(parts) != 3:
                raise RagFailure("invalid_source", "Unclosed Markdown frontmatter")
            meta = yaml.safe_load(parts[1]) or {}
            if not isinstance(meta, dict):
                raise RagFailure(
                    "invalid_source", "Source frontmatter must be a mapping"
                )
            text = parts[2].strip()
        relative = path.relative_to(directory).as_posix()
        if path.parent.name == "proposals":
            kind = "proposal"
        elif path.parent.name == "case_studies":
            kind = "case_study"
        elif path.stem.lower() == "cv":
            kind = "cv"
        elif path.stem.lower() == "reviews":
            kind = "review"
        elif path.stem.lower() == "readme":
            kind = "readme"
        elif path.suffix.lower() in CODE:
            kind = "code"
        else:
            kind = "document"
        project = meta.get("project") or (path.stem if kind == "case_study" else None)
        documents.append(
            Document(
                id=f"{persona}:{relative}",
                persona=persona,
                type=kind,
                source=relative,
                source_hash=source_hash(path),
                text=text,
                date=str(meta["date"]) if meta.get("date") else None,
                outcome=meta.get("outcome"),
                project=project,
                industry=meta.get("client_industry") or meta.get("industry"),
                skills=meta.get("skills", []),
            )
        )
    return documents
