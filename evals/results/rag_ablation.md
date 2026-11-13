# R&D B: V3 component ablation

Full V3 = dense + BM25 + reranking. Remove exactly one added component per comparison. The dense backbone is retained.

These configurations are experimental wrappers, not additional RAG variants. All three arms were measured fresh with the same candidate limit. No Qwen grading, decomposition, or verification calls are used.

Quality metrics exclude no-evidence queries; abstention is reported separately. Failures count as zero quality, not successful abstention. Labels are provisional until reviewed. Per-persona/type summaries and full-minus-ablated paired effects are in the JSON report. Production selection remains with the user.

## Paired component effects

- Full V3 minus without_reranker: mean nDCG@10 difference 0.0449, 95% bootstrap interval [0.00509537794236128, 0.09167322659866547].
- Full V3 minus without_bm25: mean nDCG@10 difference 0.0098, 95% bootstrap interval [0.0, 0.02934090250806566].


| configuration | recall_at_5 | mrr | ndcg_at_10 | correct_abstention | p50_seconds | p95_seconds | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_v3 | 0.9444 | 0.9074 | 0.9143 | 0 | 0.7492 | 0.9873 | 0 |
| without_reranker | 0.9074 | 0.8556 | 0.8694 | 0 | 0.1152 | 0.1938 | 0 |
| without_bm25 | 0.9259 | 0.9074 | 0.9045 | 0 | 0.7956 | 1.1115 | 0 |
