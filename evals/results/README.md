# RAG evaluation artifacts

`rag_comparison.csv` is the exact eight-column B5 table, one row per variant.
`rag_comparison.json` is the unified summary: retrieval, B3 claim verification,
quality judging/calibration, simulated outcomes, timing/tokens and component
ablation. `rag_comparison.md` and README are generated from those saved stages.
Use `make rag-table` to regenerate offline; no model calls are made.

The JSON records artifact_directory for the active run and hashes its sources.
Imported original retrieval/workflow measurements and completed human scores are
preserved; `rag_import.json` records provenance. `proposal/` and historical
JSONL files are historical source evidence, not another active evaluation.
The imported retrieval queries and fixed GigSim jobs are different fixtures.
Labels remain provisional; judge means include observed human agreement.
No shipped variant is selected automatically and hardware cost remains unknown.

`make rag-eval` creates a fresh run under runs/<timestamp>/, executes all stages
and ablation, and publishes complete results here. `--resume DIR` continues an
interrupted compatible run. `make rag-calibrate` imports one overall human score
per item from the active run's rag_human_review.csv; old labels are not replaced.

The completed rag_rd_b.* V2–V3 hypothesis study remains separate. Historical
rag_ablation.* evidence is reused for the import; future rag-eval runs measure
component ablation automatically. Neither table generation nor calibration
reruns the R&D study or ablation.


## Corrected runtime and client fixtures

The published imported comparison remains historical. Its 44 embedding failures
used an incorrect 512-token budget for a runtime configured at 256, and all 42
submissions were rejected for skill mismatch. The report now exposes those
failure categories and reconstructed reply gates without changing any outcomes.

Future runs use evals/datasets/rag_jobs_v2.json, with coherent client assignments
for the same public jobs. `make rag-repair-data` can regenerate this version and
separate processed seed files without model calls. Preflight verifies runtime
limits and positive/negative MCP simulator controls; controls are not benchmark
observations. Run `make rag-eval` for fresh measurements and provide new human
scores for its drafts. Existing results and human labels remain unchanged.
