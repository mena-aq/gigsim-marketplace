# RAG result artifacts

rag_comparison.json is the completed comparison source of truth. Its observations
field names the exact raw timestamped JSONL run. CSV/Markdown tables are generated
from that JSON using `make rag-table`. Labels remain agent-authored and provisional.
The user has not selected a winning variant. No outcomes or calibrated judge scores
are fabricated. Interrupted diagnostic runs are not pooled into completed aggregates; each
report names the exact source run.

## Quick R&D B outputs

Run evals.runners.rag_rd_b with an explicit --run JSONL argument for an offline
paired V3/V2 analysis. It writes rag_rd_b.json, .csv, .md, paired query evidence,
and a scoring-dataset snapshot. Run evals.runners.rag_ablation manually for fresh
full-V3 / without-reranker / without-BM25 measurements. Its timestamped raw JSONL
and rag_ablation reports are separate from the five-variant comparison above.
Results are exploratory and labels remain provisional until reviewed. Source runs
are never rewritten, and no production variant is chosen automatically.
