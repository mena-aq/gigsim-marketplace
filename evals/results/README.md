# RAG result artifacts

rag_comparison.json is the completed comparison source of truth. Its observations
field names the exact raw timestamped JSONL run. CSV/Markdown tables are generated
from that JSON using `make rag-table`. Labels remain agent-authored and provisional.
The user has not selected a winning variant. No outcomes or calibrated judge scores
are fabricated. Incomplete diagnostic runs are kept locally under ignored generated
data rather than pooled into the published aggregate.
