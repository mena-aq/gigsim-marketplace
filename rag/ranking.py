"""BM25 and reciprocal rank fusion, kept independent of model inference."""

import math
import re
from collections import Counter

from rag.types import Hit


def terms(text: str) -> list[str]:
    return [
        term.strip(".-")
        for term in re.findall(r"[\w+#.-]+", text.casefold())
        if term.strip(".-")
    ]


def bm25(query: str, chunks: list, k: int) -> list[Hit]:
    if not chunks:
        return []
    documents = [Counter(terms(chunk.text)) for chunk in chunks]
    sizes = [sum(document.values()) for document in documents]
    average = sum(sizes) / len(sizes) or 1
    frequency = Counter(word for document in documents for word in document)
    hits = []
    for chunk, document, size in zip(chunks, documents, sizes, strict=True):
        score = 0.0
        for word in set(terms(query)):
            count = document[word]
            if not count:
                continue
            inverse = math.log(
                1 + (len(documents) - frequency[word] + 0.5) / (frequency[word] + 0.5)
            )
            score += (
                inverse * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * size / average))
            )
        if score > 0:
            hits.append(Hit(chunk=chunk, score=score))
    return sorted(hits, key=lambda item: (-item.score, item.chunk.chunk_id))[:k]


def fuse(rankings: list[list[Hit]], constant: int, k: int) -> list[Hit]:
    scores = {}
    chunks = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit.chunk.chunk_id
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0) + 1 / (constant + rank)
            chunks[key] = hit.chunk
    return [
        Hit(chunk=chunks[key], score=scores[key])
        for key in sorted(scores, key=lambda key: (-scores[key], key))[:k]
    ]


def unique_items(hits: list[Hit], k: int) -> list[Hit]:
    seen = set()
    result = []
    for hit in hits:
        if hit.chunk.id not in seen:
            seen.add(hit.chunk.id)
            result.append(hit)
            if len(result) == k:
                break
    return result
