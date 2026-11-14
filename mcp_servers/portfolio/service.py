"""Read-only assigned portfolio resources and configurable RAG retrieval."""

from pathlib import Path

from mcp_servers.common.security import ToolFailure


class PortfolioService:
    def __init__(self, root: Path, *, pipeline_factory=None, retired_loader=None):
        self.root = root.resolve()
        self.pipeline_factory = pipeline_factory
        self.retired_loader = retired_loader

    async def scoped_pipeline(self, who):
        pipeline = self.pipeline(who)
        if self.retired_loader is not None:
            pipeline.retired = frozenset(await self.retired_loader(who))
        return pipeline

    def pipeline(self, who):
        if self.pipeline_factory is not None:
            return self.pipeline_factory(who)
        from rag.config import load_config
        from rag.retriever import Pipeline

        return Pipeline(load_config(), self.root, who.user_id, who.persona)

    def directory(self, who):
        path = (self.root / who.persona).resolve()
        if path.parent != self.root or not path.is_dir():
            raise ToolFailure(
                "corpus_unavailable",
                "Assigned persona corpus is missing; generate or mount it first",
            )
        return path

    def items(self, who):
        from rag.ingest.loaders import load_documents

        return [
            document.model_dump(exclude={"source_hash"})
            for document in load_documents(self.root, who.persona)
        ]

    async def search(self, who, request):
        result = await (await self.scoped_pipeline(who)).retrieve(
            request.requirement, request.k, request.filters.model_dump()
        )
        return {
            "items": [
                {**hit.chunk.model_dump(exclude={"source_hash"}), "score": hit.score}
                for hit in result.hits
            ],
            "backend": result.variant,
            "retrieval_status": result.status,
            "diagnostics": result.diagnostics,
        }

    async def verify(self, who, request):
        from rag.verify import verify_claims

        pipeline = await self.scoped_pipeline(who)
        evidence = await pipeline.evidence(request.chunk_ids)
        return (await verify_claims(request.draft, evidence, pipeline.llm)).model_dump()

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
