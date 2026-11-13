# R&D B: reranking hypothesis

Adding cross-encoder reranking to hybrid retrieval improves mean nDCG@10.

Exploratory results; labels reviewed: False.

Primary comparison: V3 minus V2 on 27 positive queries.
Mean paired difference: 0.0449; 95% bootstrap interval: [0.00509537794236128, 0.09167322659866547].
Outcome: observed_improvement. The interval is above zero: this development set favors reranking on nDCG@10.

No-evidence queries are excluded from ranking metrics.

Latency is copied from the saved run; this script makes no model or database calls.
Rankings are re-scored against the supplied labels. Keep the original query text for each ID.
Per-persona/type deltas, failures, and per-query evidence are in the JSON files.

| configuration | recall_at_5 | mrr | ndcg_at_10 | correct_abstention | p50_seconds | p95_seconds | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v2 | 0.9074 | 0.8556 | 0.8694 | 0 | 0.1522 | 0.2343 | 0 |
| v3 | 0.9444 | 0.9074 | 0.9143 | 0 | 0.9089 | 1.3306 | 0 |
