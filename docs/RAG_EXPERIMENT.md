# One RAG evaluation for Part B

`make rag-eval` evaluates V0, V1, V2, V3 and V8 in one run. B3 claim verification
is a stage of this evaluation and supplies B5's unsupported-claim measurements.
Component ablation runs at the end. The completed V2–V3 R&D hypothesis study is
separate and is not rerun automatically.

## Fixtures and execution

The benchmark uses 30 labelled retrieval queries (ten per persona), 12 controlled
claim-regression examples, and 30 fixed GigSim jobs (ten per persona). Future runs use rag_jobs_v2.json,
which preserves public jobs while repairing client associations. Query and
regression labels remain agent-authored and provisional. Jobs were sampled with
seed 42 from the processed data, excluding flagged scams/injections and job
texts longer than 3,000 characters. Original hidden client preferences are never
passed to the writer. The fixtures are parts of one benchmark; historical query
and job measurements are not paired observations of the same jobs.

Retrieval uses the configured 200-token chunks, 40 overlap, model revisions and
user namespaces. V0 is dense; V1 selects source sentence/bullet IDs and reconstructs exact requirements; V2 uses
BM25/dense RRF; V3 reranks 20 candidates; V8 grades five candidates and may run one
corrective search. Missing/stale indexes fail explicitly rather than substituting
lexical results. Empty-label queries are excluded from ranking metrics and have
a separate correct-abstention metric. Retrieval failures score zero quality and
never count as successful abstention.

For each job/variant, retrieve evidence, write a short draft, verify claims,
independently assess original/cleaned text, judge quality, and measure a simulated
outcome. Variant order rotates per job. The same writer settings apply to every
variant. All-minilm architecture metadata advertises 512 tokens, but installed
Ollama parameters set num_ctx=256. Query inputs are therefore limited to 254
tokens plus two special tokens; long inputs are explicitly truncated by the
retriever and diagnosed. Existing 200-token chunks and vectors remain usable. Prompt text lives in agent/prompts/rag_*.md; settings live in
agent/config.yaml. No model downloads or production sends are part of evaluation.

New runs use timestamped directories with common code/configuration/fixture and
model/runtime fingerprints. Each stage flushes raw observations; resumption
preserves completed calls and failed observations. Completed stages are not
repeated. Changing code, fixtures, model/runtime or a stage's index fingerprint
requires a new run. Models execute sequentially on a shared CPU without an explicit
warmup. This is not a dedicated-hardware latency benchmark.

## B3 and B5 measurements

Claim verification splits drafts into source-quoted atomic claims and assigns
supported, partly_supported, or unsupported status using owned evidence chunks.
It verifies factual sentences individually using a schema restricted to their
index and available evidence IDs. Plain intentions/questions are retained without
generative grading. It removes unsupported/partial facts and only the sentence
affected by a failed judgment. Conservative classification, number and unchecked-text guards close
observed bypasses; they do not guarantee that a small model grades every fact
correctly. Controlled claim examples remain regression diagnostics, rather than
the generated-draft claim rates used in B5.

Independent assessment gets a separate prompt/context without verifier labels.
Plain greetings, questions and explicit future intentions are excluded from
experience counts by a conservative filter. Generation and assessment still use
the same local model, so shared bias remains possible. Report unsupported atomic
experience claims divided by assessed experience claims before and after
verification, plus unsupported claims per assessed draft. Partly supported
claims, assessment failures, empty drafts and exact-text supported retention are
recorded separately. Empty claim denominators remain undefined; a zero rate with
few assessed claims is not proof of zero hallucinations.

The primary CSV has exactly the eight assignment columns, one row per variant:
Variant, Evidence Recall@5, nDCG@10, Unsupported claims per proposal, Judge score,
GigSim reply rate, p95 latency (s), Cost per proposal (USD). MRR, p50, tokens,
counts, per-persona/category metrics, hire rate, B3 diagnostics and ablation remain
in the same JSON/Markdown report. p95 covers retrieval, drafting and verification;
it excludes evaluation-only assessment, judge calls and simulator waiting. Model
loading is included when incurred. Paid API spend is zero; total USD per proposal
is unmeasured without hardware/electricity accounting.

GigSim outcomes use real in-memory Marketplace MCP sessions and fresh in-memory
simulator/approval databases. Redis quotas and chaos are disabled for the fixture.
The job, original client preferences and per-job random seed are identical across
variants. GigSim derives skill mentions from the cleaned cover letter; the writer
cannot supply invented skill metadata. Reply rate counts replied/interview/hired
outcomes among successfully submitted proposals with completed outcomes. Report
submission failures, empty drafts, outcome failures and reply yield per attempted
job alongside it. GigSim checks skill mentions, generic openings and randomness,
not semantic proposal quality, so improved retrieval need not increase replies.
Production agent workflows will later run through the same evaluation entry point
with their workflow profile recorded separately.

## One-score human calibration

Generate a 30-item blinded pack from six scored outputs per variant, aiming for
two per persona; sparse cells are filled from other personas of that variant.
This sample represents judge-scored survivors and excludes failed/empty outputs.
The rubric asks for one overall integer score, 1–5, combining relevance,
specificity, grounding and clarity. Fill only human_score in rag_human_review.csv;
no sub-scores or comments are required. Do not inspect rag_calibration_key.json
before scoring. Existing human labels are never overwritten automatically.

`make rag-calibrate` imports all 30 real labels, validates reviewed text against
observations, and reports exact agreement and unweighted Cohen's kappa. Judge
means are published even with low agreement, explicitly labelled provisional;
the former 0.4 reference is diagnostic only. Changed proposals need a new review
pack. The separate blind pairwise classmate panel required by B4 remains pending.

## Ablation and separate R&D hypothesis

The existing hypothesis is that cross-encoder reranking improves mean nDCG@10
over hybrid retrieval. Its offline V2–V3 analysis uses paired differences on
positive queries, a 10,000-sample percentile bootstrap with seed 42, and
resampling within persona. An interval above zero is observed improvement;
covering zero is inconclusive. This exploratory development result does not prove
better replies or population-wide significance. The earlier experiment was not
preregistered or held out; no stronger claim is made now.

The main evaluation automatically measures full V3, without reranking, and
without BM25, removing one added component at a time while retaining dense
retrieval. All arms share the same chunk candidate limit (20 by default), return
at most ten unique items, rotate execution order, and use a no-generation guard.
Removing BM25 reranks the raw dense chunk pool, not V0's deduplicated output.
Full-minus-ablated effects, bootstrap intervals and persona/query-type breakdowns
are included in the RAG summary. Ablation observations are resumable. This does
not add registered RAG variants or select the shipped variant automatically.

## Commands and imported evidence

- `make rag-table`: regenerate the CSV, report and README offline.
- `make rag-calibrate`: import the active run's human scores and regenerate.
- `make rag-eval` (or `make eval`): execute the complete benchmark and ablation.
- `make rag-smoke`: execute a small check without publishing it as the full run.

Current outputs are evals/results/rag_comparison.json, .csv and .md. The JSON
records the active artifact directory and hashes every source. Historical
retrieval/workflow observations, ablation, human labels and calibration were
imported without inference. Originals under evals/results/proposal/ and historical
JSONL files are preserved as evidence. Imported measurements retain their original
fingerprints rather than pretending they came from one fresh run. The source
import manifest records the copied artifacts and hashes. See the runbook for
resume commands and prerequisites.

## Failure diagnosis and corrected data

The historical 150 attempts had 44 embedding errors and 12 unanchored
requirement-extraction errors. All 42 submissions were rejected at GigSim's
skill gate: random job/client assignments left 29/30 public job skill sets
incompatible with their clients. This did not measure real response quality.

Data generation now weights job assignment only among skill-compatible clients,
adding deterministic category-specific profiles where coverage is missing.
Bad actors remain eligible; profiles are never chosen from observed replies.
`make rag-repair-data` applies the same matching policy to existing processed
inputs, writes separate seed files under data/processed/repaired_clients/, and
freezes rag_jobs_v2.json. It preserves all 30 job IDs/public fields, existing
client profiles, original snapshots, measured results and human scores. The
repaired 1,500-job seed has 209 clients (nine coverage profiles beyond the 200
originals). Existing bad actors remain present; no reply rules were changed.

Before model inference, preflight checks every job/client skill intersection,
the embedding runtime budget, a boundary embedding, and real MCP positive and
negative reply controls in fresh fixtures. Control outcomes are excluded from
measured reply rates. A compatible control may reply, while an actual draft
that omits the matching public skill is still rejected. Do not force a nonzero
benchmark rate or provide hidden preferences to the writer.

JSON/Markdown diagnostics distinguish embedding/decomposition/structured-model
failures, verifier and assessment errors, empty drafts, low-hire-rate and skill
rejections, generic openings, and eligible-but-no-reply outcomes. Old reply gates
can be reconstructed from saved inputs without rewriting outcomes. Changed drafts
from a new run require a fresh human review pack; old scores are not transferable.
