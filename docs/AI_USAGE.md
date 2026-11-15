# AI Usage Disclosure

### Part C orchestration

Codex implemented the bid/conversation StateGraphs, structured node handoffs,
file-backed prompts/policies, Postgres checkpoints and memory, worker outbox,
authenticated run/review API, generated TypeScript contract, and minimal review
page. Focused tests use deterministic model outputs and isolated simulators;
they are not published as model-quality measurements. During implementation,
Codex initially seeded replay state using `as_node=END`, which the installed
LangGraph version rejects. The Postgres replay test caught this; seeding through
the real terminal `stop` node fixed it while preserving a fresh approval gate.
No 50-job comparison or RAG benchmark was run for this milestone.

Real user runs subsequently exposed arbitrary risk scores despite empty risk
flags, invented long evidence IDs, omitted screening answers, and verifier CPU
timeouts. Codex inspected the saved traces and replaced free-form risk scores
with source-quoted findings and configured levels, constrained matcher citations,
bounded Writer output and screening schemas, and routed verification repairs
through the existing revision limit. The earlier smoke tests did not establish
end-to-end model reliability. Regression tests now cover these observed failures;
unsupported/unverified claims remain blocked rather than admitted to make runs pass.

The live diagnosis also found the Compliance Guard labelling verified past
metrics and timeline estimates as contact details/guarantees. Its model output
now requires a concrete quoted finding, with explicit policy distinctions, while
deterministic checks remain active. Coverage retries fix the exact whole sentence
in the decoder; they still enforce numeric and citation validation. Future-intent
recognition was extended for observed readiness/estimate phrasing, with tests
rejecting embedded past achievements. A repaired job subsequently completed the
full graph after a recorded authenticated approval; no approval was issued by
the diagnostic scripts.

Record the AI coding assistant/tool used, the files or tasks it helped with, and at least
one incorrect suggestion you identified and corrected. You remain responsible for all code.

## Step 1 foundation

OpenAI Codex implemented the API readiness checks, app schema and migrations,
Arq worker smoke path, Next.js shell and generated contract tooling, Compose
services, lockfiles, tests, and setup/architecture documentation. Existing
GigSim source was preserved; its Docker dependency declaration gained the same
SQLAlchemy async extra needed by the application.

Correction during implementation: the initial dependency declaration used
plain SQLAlchemy, which omitted the greenlet dependency needed by async engine
support. The import failure was caught and the declaration changed to
`sqlalchemy[asyncio]`. Documentation also corrected an existing HTMX architecture
statement that conflicted with the assignment's React/Next.js requirement.

The user clarified that Ollama/qwen2.5:3b was already installed on the host.
A duplicate Ollama image pull exhausted disk space during verification; that
newly downloaded image was removed, the interrupted Compose write restored,
and the configuration changed to a small bridge to the existing host service.
The full stack and PostgreSQL tests were checked again after recovery.

## Step 2 MCP layer

OpenAI Codex implemented the three MCP servers, shared contracts/auth/audit/write
receipts, typed MCP client/port, migration, Compose wiring, tests and documentation.
The owner authorized the narrow GigSim idempotency/concurrency changes and chose
to exclude Upwork, defer GitHub, and use a persistent local Workspace mock.

One caught error: the first resource reader treated a URI-encoded evidence ID as
its literal file ID, so the protocol test returned not_found. Resource handlers
now decode template arguments before the persona/path checks, and the regression
reads the resource through the actual in-memory MCP client.

## Step 3 RAG pipeline

OpenAI Codex implemented ingestion/chunking, Chroma manifests, the five retrieval
variants, Ollama/CPU ONNX adapters, structured claim verification, MCP integration,
provisional datasets/evaluation runners, tests, and documentation. No variant was
automatically selected. Corpus generation, Upwork and GitHub were not added.

Caught issues included an older lexical-search test expecting no dense neighbours,
a sentence-ending punctuation mismatch in BM25 tokenization, and unanchored
missing-requirement text returned by the local grader. Tests/handling were updated:
dense baseline behavior is explicit, lexical punctuation is normalized, and
invented correction terms are discarded. Early diagnostic runs were interrupted
for correctness/resource changes; only the final fixed-fingerprint run feeds the
published comparison. Numeric-claim checks supplement, rather than replace, the
small model's provisional semantic judgments.

## Quick R&D B study scripts

OpenAI Codex added the offline V3-versus-V2 paired hypothesis analysis, the fresh
three-arm V3 ablation, input validation, fixed-seed paired bootstrap intervals,
automatic JSON/CSV/Markdown reports, and synthetic correctness tests. The user runs
the actual studies; the assistant did not execute either on real development data.

One implementation concern checked explicitly: removing BM25 must pass the raw
dense chunk pool to the reranker. Reusing V0's final deduplicated documents would
change two pipeline stages and invalidate the one-component ablation. A toy
candidate-pool test verifies the full and ablated paths and matching pool limits.

### B3/B5 evaluation harness

Codex added conservative verification classification/coverage checks, isolated
Marketplace MCP/GigSim outcome evaluation, a frozen proposal dataset, independent
claim assessment, and report/calibration tooling. During review, the first draft
reused verification retention rules for independent assessment, which would count
ordinary questions as unsupported facts. This was corrected by separating raw
assessment validation from the verifier's removal policy. The human review uses
one overall 1–5 score; no human labels or calibrated results are fabricated.


### Unified Part B evaluation

Codex consolidated the accidentally separate proposal/retrieval commands into
one RAG evaluation and exact B5 export, with B3 metrics and component ablation in
the same report. Existing measurements, original fingerprints and completed human
scores were imported without inference. The original split and its overly strict
review sampling were corrected. Judge agreement remains visible even when low;
publication no longer requires a kappa threshold. Tests cover import integrity,
CSV shape, calibration binding and stage resumption without using fake models
as published evidence.


### Runtime and benchmark failure repair

Codex diagnosed 44 embedding failures by comparing configured context (512) to
installed num_ctx (256) and probing the boundary. It replaced copied requirement
text with source-ID selection, isolated verifier failures by sentence, constrained
verifier output citations/indexes, and repaired random client assignment at the
data generator. A separately generated v2 snapshot preserves the public jobs and
original evidence. The initial live smoke's supported claim was rejected by the
old unconstrained response format; constraining source/citation schema made the
known-supported check pass without relaxing evidence rules. Positive/negative
simulator controls are diagnostic and excluded from reported reply rates.
