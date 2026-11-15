"""Small Chroma HTTP adapter. All data calls include the authenticated namespace."""

import httpx

from rag.types import RagFailure

BASE = "/api/v2/tenants/default_tenant/databases/default_database/collections"


class Chroma:
    def __init__(self, url: str):
        self.url = url

    async def request(self, method: str, path: str, data=None):
        try:
            async with httpx.AsyncClient(base_url=self.url, timeout=60) as client:
                response = await client.request(method, path, json=data)
                response.raise_for_status()
                return response.json() if response.content else None
        except (httpx.HTTPError, ValueError):
            raise RagFailure(
                "index_unavailable",
                "Chroma is unavailable or its response is invalid",
                True,
            ) from None

    async def collection(self, name: str) -> str:
        result = await self.request(
            "POST",
            BASE,
            {"name": name, "get_or_create": True, "metadata": {"hnsw:space": "cosine"}},
        )
        return result["id"]

    async def upsert(self, collection: str, user_id: str, records: list[dict]) -> None:
        for offset in range(0, len(records), 100):
            batch = records[offset : offset + 100]
            await self.request(
                "POST",
                BASE + f"/{collection}/upsert",
                {
                    "ids": [item["chunk"]["chunk_id"] for item in batch],
                    "embeddings": [item["embedding"] for item in batch],
                    "documents": [item["chunk"]["text"] for item in batch],
                    "metadatas": [
                        {
                            "user_id": user_id,
                            "item_id": item["chunk"]["id"],
                            "type": item["chunk"]["type"],
                            "outcome": item["chunk"]["outcome"] or "",
                        }
                        for item in batch
                    ],
                },
            )

    async def delete(self, collection: str, user_id: str, ids: list[str]) -> None:
        if ids:
            await self.request(
                "POST",
                BASE + f"/{collection}/delete",
                {"ids": ids, "where": {"user_id": user_id}},
            )

    async def query(
        self,
        collection: str,
        user_id: str,
        embedding: list[float],
        k: int,
        filters: dict,
    ) -> list[tuple[str, float]]:
        conditions = [{"user_id": user_id}] + [
            {key: value} for key, value in filters.items() if value is not None
        ]
        where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
        result = await self.request(
            "POST",
            BASE + f"/{collection}/query",
            {
                "query_embeddings": [embedding],
                "n_results": k,
                "where": where,
                "include": ["distances"],
            },
        )
        return list(
            zip(
                result["ids"][0],
                [1 - float(distance) for distance in result["distances"][0]],
                strict=True,
            )
        )
