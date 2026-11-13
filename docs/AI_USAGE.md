# AI Usage Disclosure

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
