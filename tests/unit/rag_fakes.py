"""Deterministic test substitutes. Never used for published retrieval measurements."""

import json
import re
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer, models, pre_tokenizers

from rag.config import load_config

VOCAB = (
    "python",
    "forecasting",
    "pandas",
    "stripe",
    "react",
    "sql",
    "celery",
    "dbt",
    "legal",
    "fraud",
    "logistics",
    "retail",
    "churn",
    "image",
    "support",
)


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0
        self.current_digest = "test-only-digest"

    async def digest(self):
        return self.current_digest

    async def embed(self, texts):
        self.calls += len(texts)
        vectors = []
        for text in texts:
            words = re.findall(r"\w+", text.lower())
            vector = np.array(
                [words.count(word) for word in VOCAB] + [0.01], dtype=float
            )
            vector /= np.linalg.norm(vector)
            vectors.append(vector.tolist())
        return vectors


class MemoryChroma:
    def __init__(self):
        self.rows = {}
        self.names = {}
        self.queried_users = []

    async def collection(self, name):
        self.names[name] = name
        return name

    async def upsert(self, collection, user_id, records):
        rows = self.rows.setdefault((collection, user_id), {})
        rows.update({row["chunk"]["chunk_id"]: row for row in records})

    async def delete(self, collection, user_id, ids):
        for key in ids:
            self.rows[(collection, user_id)].pop(key, None)

    async def query(self, collection, user_id, embedding, k, filters):
        self.queried_users.append(user_id)
        rows = self.rows.get((collection, user_id), {})
        results = [
            (key, float(np.dot(embedding, row["embedding"])))
            for key, row in rows.items()
            if all(row["chunk"][key] == value for key, value in filters.items())
        ]
        return sorted(results, key=lambda item: (-item[1], item[0]))[:k]


class FakeReranker:
    def score(self, query, texts):
        terms = set(query.lower().split())
        return [float(len(terms & set(text.lower().split()))) for text in texts]


class FakeLLM:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.usage = []
        self.payloads = []

    async def ask(self, prompt, payload, schema):
        self.usage.append(
            {
                "prompt": prompt,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "seconds": 0,
                "evaluation_seconds": 0,
            }
        )
        self.payloads.append(payload)
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return schema.model_validate(answer)
        if prompt == "rag_decompose":
            return schema.model_validate({"ids": [payload["segments"][0]["id"]]})
        if prompt == "rag_grade":
            return schema.model_validate(
                {
                    "grade": "adequate",
                    "evidence_ids": [item["id"] for item in payload["evidence"]],
                    "missing_requirements": [],
                    "reason": "test-only",
                }
            )
        return schema.model_validate(
            {
                "sentences": [
                    {
                        "index": item["index"],
                        "claims": [
                            {
                                "text": item["text"],
                                "kind": "experience",
                                "status": "supported"
                                if payload["evidence"]
                                else "unsupported",
                                "evidence_ids": [payload["evidence"][0]["id"]]
                                if payload["evidence"]
                                else [],
                                "reason": "test-only",
                            }
                        ],
                    }
                    for item in payload["sentences"]
                ]
            }
        )


def test_config(tmp_path: Path):
    config = load_config().model_copy(
        update={"data_dir": tmp_path / "rag", "embedding_dimensions": 16}
    )
    path = config.data_dir / "models/embedding/tokenizer.json"
    path.parent.mkdir(parents=True)
    tokenizer = Tokenizer(
        models.WordLevel(
            {"[UNK]": 0, **{word: i + 1 for i, word in enumerate(VOCAB)}},
            unk_token="[UNK]",
        )
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(path))
    (config.data_dir / "models/manifest.json").write_text(
        json.dumps({"tokenizer_revision": config.tokenizer_revision})
    )
    return config
