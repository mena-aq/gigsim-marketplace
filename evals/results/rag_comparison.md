## RAG evaluation — B3, B5 and ablation

Run status: complete. Workflow: RAG benchmark.

One evaluation covers retrieval, drafting, claim verification, quality judging, and simulated replies. The imported measurements use labelled retrieval queries and a fixed GigSim job set; they are separate fixtures, not paired observations of the same jobs. p95 covers retrieval → drafting → verification and excludes assessment, judging and simulator waiting. Paid API spend is zero for local inference; total hardware cost is unmeasured.

Judge calibration: 30 human scores; exact agreement 10.0%; Cohen's κ = 0.031. Judge means are published alongside agreement; low agreement makes them provisional.

| Variant | Evidence Recall@5 | nDCG@10 | Unsupported claims per proposal | Judge score | GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 0.815 | 0.738 | 0.000 | 3.692 | 0.000 | 119.263 | not measured |
| v1 | 0.704 | 0.625 | 0.000 | 3.857 | 0.000 | 151.708 | not measured |
| v2 | 0.907 | 0.869 | 0.000 | 3.375 | 0.000 | 118.413 | not measured |
| v3 | 0.944 | 0.914 | 0.000 | 3.571 | 0.000 | 125.371 | not measured |
| v8 | 0.815 | 0.787 | 0.000 | 3.714 | 0.000 | 245.830 | not measured |

### Claim verification and outcome denominators

| Variant | Assessed drafts | Unsupported before | Unsupported after | Supported retention | Failures | Submitted | Replies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 13 | 0/4 (0.000) | 0/4 (0.000) | 0.500 | 11 | 13 | 0 |
| v1 | 8 | 0/0 (not measured) | 0/0 (not measured) | not measured | 12 | 7 | 0 |
| v2 | 7 | 0/3 (0.000) | 0/2 (0.000) | 1.000 | 11 | 8 | 0 |
| v3 | 10 | 0/3 (0.000) | 0/1 (0.000) | 0.500 | 11 | 7 | 0 |
| v8 | 8 | 0/6 (0.000) | 0/2 (0.000) | 0.333 | 13 | 7 | 0 |

Unsupported rates use independently assessed atomic experience claims; partly supported claims and incomplete assessments are recorded in JSON. An empty denominator is undefined. A zero unsupported count with few assessed claims does not establish zero hallucination risk. Supported retention uses exact claim text and may be affected by segmentation.

Reply rate = replied/interview/hired outcomes divided by submitted proposals with completed outcomes. Empty drafts and failed submissions are excluded from that denominator; JSON also records reply yield per attempted job, empty drafts, and outcome failures. GigSim runs in fresh in-memory fixtures through real MCP tools, with the same job/client/random seed for each variant and skill mentions derived from the cleaned text. It checks skill mentions, generic openings and randomness, not semantic proposal quality.

### Failure and reply-gate breakdown

| Variant | Embedding failures | Decomposition failures | Other model failures | Verifier errors | Assessment failures | Skill rejects | Eligible no-reply |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0 | 11 | 0 | 0 | 5 | 6 | 13 | 0 |
| v1 | 0 | 12 | 0 | 7 | 10 | 7 | 0 |
| v2 | 11 | 0 | 0 | 8 | 12 | 8 | 0 |
| v3 | 11 | 0 | 0 | 11 | 9 | 7 | 0 |
| v8 | 11 | 0 | 2 | 8 | 9 | 7 | 0 |

Verifier/assessment errors may overlap a completed draft and are not added to job failures. Historical reply gates are reconstructed from the saved job/client/draft; this does not change the recorded outcome.

### Component ablation

Full V3 = dense + BM25 + reranking. Positive full-minus-ablated deltas favor the retained component. This retrieval-only component test runs within rag-eval; it does not generate extra proposals.

| Component removed | Paired nDCG@10 delta | 95% bootstrap interval |
| --- | --- | --- |
| without_reranker | 0.0449 | [0.00509537794236128, 0.09167322659866547] |
| without_bm25 | 0.0098 | [0.0, 0.02934090250806566] |

Per-persona/category results, MRR, p50, tokens, partial support, hire rate and failures are in the JSON. The production agent graph and blind pairwise classmate panel remain future work. No shipped variant has been selected.

Sources:

- [rag_retrieval.json](rag_retrieval.json)
- [rag_retrieval_observations.jsonl](rag_retrieval_observations.jsonl)
- [rag_workflow.json](rag_workflow.json)
- [rag_workflow_observations.jsonl](rag_workflow_observations.jsonl)
- [rag_jobs.json](rag_jobs.json)
- [rag_judge_calibration.json](rag_judge_calibration.json)
- [rag_human_review.csv](rag_human_review.csv)
- [rag_ablation.json](rag_ablation.json)
- [rag_import.json](rag_import.json)

The completed [V2–V3 R&D hypothesis study](rag_rd_b.md) remains separate and is not rerun by rag-eval.
