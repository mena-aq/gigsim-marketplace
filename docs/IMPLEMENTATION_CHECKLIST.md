# Student Implementation Checklist

- [x] Read the assignment and the supplied GigSim documentation.
- [x] Step 1: runnable web/API/worker foundation, migrations, Compose and contracts.
- [ ] Step 0 follow-up: expand each persona beyond 8 case studies / 50 proposals.
- [ ] Step 0 follow-up: verify simulator write concurrency and idempotency on Postgres.
- [x] Implement the marketplace port and GigSim adapter.
- [x] Implement Portfolio MCP tools, resources and prompts (interim lexical search).
- [x] Implement Marketplace MCP tools, schemas, idempotency, and approval enforcement.
- [x] Implement Workspace MCP tools with a persistent local mock.
- [x] Ingest local CVs, case studies, READMEs/code, reviews and past proposals (GitHub deferred).
- [x] Implement exactly V0, V1, V2, V3, V8.
- [x] Implement claim splitting and evidence verification through Portfolio MCP.
- [x] Implement the bid graph with parallel analysis branches.
- [x] Implement the conversation graph.
- [x] Add bounded Critic loop and Compliance Guard.
- [x] Add LangGraph interrupts for all external actions and Connects spend.
- [x] Add durable checkpointing and crash/resume test.
- [ ] Build all required UI screens and approval interactions.
- [ ] Add worker scheduling, tracing, budgets and guardrails.
- [ ] Add unit, integration, contract and Playwright tests.
- [ ] Run evaluations and commit reproducible results.
- [ ] Deploy and verify reviewer access.
- [ ] Complete report, demo, technical write-up and AI usage disclosure.

- [ ] Manually capture MCP Inspector screenshots (instructions in docs/TOOLS.md).
- [ ] Run tool-design study and grounded-agent demo after retrieval/graphs exist.
- [ ] Add durable graph requeueing and degraded-mode UI in later milestones.

- [ ] Human-review provisional retrieval and claim labels, then select the active variant.
- [ ] Run full production agent evaluation in later milestones.

### One RAG evaluation for Part B

- [x] Close observed nonfactual/intent classification bypass; reject unchecked text.
- [x] Include drafting, verification, independent assessment, judge and isolated MCP outcomes in rag-eval.
- [x] Import completed measurements and 30 real human scores without inference.
- [x] Generate the exact eight-column B5 CSV and B3 denominators in one report.
- [x] Include resumable component ablation in the main evaluation.
- [x] Report judge agreement and publish measured means even with low agreement.
- [ ] Run the separate blind pairwise human panel and production graph evaluation.


### Evaluation failure repair

- [x] Correct embedding context to 256 / 254 content tokens and classify failures.
- [x] Select V1 requirements by source IDs; verify factual sentences individually.
- [x] Generate compatible client associations and preserve fixed public jobs in v2.
- [x] Add real embedding and simulator preflight controls and failure/gate reporting.
- [ ] User-run full corrected benchmark and supply fresh human scores for its drafts.
