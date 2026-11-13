"""Read-only persona corpus access with stable IDs and interim lexical ranking."""

import re
from pathlib import Path

import yaml

from mcp_servers.common.security import ToolFailure


class PortfolioService:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def directory(self, who):
        path = (self.root / who.persona).resolve()
        if path.parent != self.root or not path.is_dir():
            raise ToolFailure(
                "corpus_unavailable",
                "Assigned persona corpus is missing; generate or mount it first",
            )
        return path

    def items(self, who):
        directory = self.directory(who)
        paths = [directory / "cv.md", directory / "reviews.md"]
        paths += sorted((directory / "case_studies").glob("*.md"))
        paths += sorted((directory / "proposals").glob("*.md"))
        items = []
        for path in paths:
            resolved = path.resolve()
            if (
                not resolved.is_relative_to(directory)
                or not path.is_file()
                or path.stat().st_size > 262144
            ):
                continue
            text = path.read_text(encoding="utf-8")
            meta = {}
            if text.startswith("---\n"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    try:
                        meta = yaml.safe_load(parts[1]) or {}
                    except yaml.YAMLError:
                        raise ToolFailure(
                            "invalid_corpus", "A portfolio item has invalid metadata"
                        ) from None
                    text = parts[2].strip()
            if not isinstance(meta, dict):
                raise ToolFailure(
                    "invalid_corpus", "Portfolio metadata must be a mapping"
                )
            kind = {"case_studies": "case_study", "proposals": "proposal"}.get(
                path.parent.name, "cv" if path.name == "cv.md" else "review"
            )
            relative = path.relative_to(directory).as_posix()
            items.append(
                {
                    "id": f"{who.persona}:{relative}",
                    "persona": who.persona,
                    "type": kind,
                    "source": relative,
                    "text": text,
                    "date": str(meta["date"]) if meta.get("date") else None,
                    "outcome": meta.get("outcome"),
                    "project": path.stem if kind == "case_study" else None,
                    "skills": meta.get("skills", []),
                }
            )
        return items

    async def search(self, who, request):
        terms = set(re.findall(r"[\w+#.-]+", request.requirement.lower()))
        scored = []
        for item in self.items(who):
            if any(
                value is not None and item[key] != value
                for key, value in request.filters.model_dump().items()
            ):
                continue
            words = set(re.findall(r"[\w+#.-]+", item["text"].lower()))
            score = len(terms & words)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        return {
            "items": [
                {**item, "text": item["text"][:1200]} for _, item in scored[: request.k]
            ],
            "backend": "lexical",
        }

    async def get(self, who, item_id, kind):
        if (
            not item_id.startswith(who.persona + ":")
            or ".." in item_id
            or "\\" in item_id
        ):
            raise ToolFailure("not_found", "Portfolio item not found")
        for item in self.items(who):
            if item["id"] == item_id and item["type"] == kind:
                return item
        raise ToolFailure("not_found", "Portfolio item not found")

    async def skills(self, who):
        path = self.directory(who) / "skills.json"
        if not path.is_file() or not path.resolve().is_relative_to(self.directory(who)):
            raise ToolFailure(
                "corpus_unavailable", "Assigned persona skills are missing"
            )
        import json

        try:
            data = json.loads(path.read_text())
            skills = data["skills"]
            if not isinstance(skills, list) or not all(
                isinstance(value, str) for value in skills
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ToolFailure(
                "invalid_corpus", "Persona skills must be a list of strings"
            ) from None
        return {"skills": skills}
