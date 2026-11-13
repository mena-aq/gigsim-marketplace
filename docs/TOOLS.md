# MCP tool inventory — Step 2

GigSim is the only marketplace. Upwork and GitHub integrations are intentionally
excluded/deferred by the project owner. No scraping or external email sending.
All HTTP MCP endpoints require a provisioned bearer token with the `gigbid` scope.
Identity and assigned persona come from the token, never caller-supplied user IDs.

| Tool | Server | Access | readOnly / destructive / idempotent / openWorld | Backend |
| --- | --- | --- | --- | --- |
| search_evidence | Portfolio | read | true / false / true / false | Assigned persona files |
| get_case_study | Portfolio | read | true / false / true / false | Assigned persona files |
| list_skills | Portfolio | read | true / false / true / false | Assigned persona skills |
| search_jobs | Marketplace | read | true / false / true / true | GigSim jobs |
| get_job | Marketplace | read | true / false / true / true | GigSim job |
| get_client_history | Marketplace | read | true / false / true / true | Public client history |
| get_connects_balance | Marketplace | read | true / false / true / true | Authenticated freelancer |
| list_messages | Marketplace | read | true / false / true / true | Owned conversation |
| create_proposal_draft | Marketplace | write | false / false / true / true | Local proposal + upstream quote |
| submit_proposal | Marketplace | write | false / true / true / true | Approval-gated GigSim submission |
| send_message | Marketplace | write | false / true / true / true | Approval-gated GigSim message |
| get_free_slots | Workspace | read | true / false / true / false | Local calendar mock |
| create_hold | Workspace | write | false / false / true / false | Local tentative hold |
| create_email_draft | Workspace | write | false / false / true / false | Local email draft, never sent |

All tools expose generated input and output JSON schemas. Common output is
`{ok, data, error, trace_id}`; `data` has a tool-specific schema. Errors contain
`code`, `message`, `retryable`, and optional `retry_after`. MCP protocol/validation
auth failures use their native error mechanisms. Argument models reject unknown
fields; IDs and strings are bounded. See `tests/contract/mcp_schemas.json` for the
complete wire contracts. Mutations take a `request` object with `idempotency_key`
and `dry_run`; most read arguments are direct, while search tools take `request`.

## Portfolio

`search_evidence` accepts requirement, k (1–20), and type/outcome filters. The
interim backend is deterministic lexical term overlap; zero matches returns no
evidence. It is not the Step 3 dense baseline and has no claimed retrieval scores.
Case studies, proposals, CV, and reviews have stable persona-relative IDs. Unknown
dates/outcomes are null; no metadata is fabricated. Corpora are mounted read-only.
Missing corpora produce `corpus_unavailable`; paths and symlinks cannot escape the
assigned persona directory. Resource URIs URL-encode the full evidence ID:
`portfolio://case/{id}` and `portfolio://proposal/{id}`. The screening-question
prompt is loaded from `agent/prompts/portfolio_screening.md`.

## Approval and idempotency

Creating local proposal/email drafts and calendar holds has no external recipient.
A dry run never creates a receipt, draft, hold, message, proposal, or Connects debit;
it still creates a masked audit event and consumes upstream request quota.
Submission preview includes the exact upstream payload and Connects cost. Set
`expected_connects_cost` to that cost for a real proposal submission.

Actual proposal/message sends require an unexpired, unconsumed database approval
grant bound to user, tool, idempotency key, and the SHA-256 canonical payload hash
(excluding only `dry_run`). No MCP tool, CLI, or public API issues grants. Normal
sends remain `approval_required` until the later human UI/graph issues them.
Automated tests create fixture grants in isolated data; they do not implement an
approval bypass. There is no `approved=true` argument.

A per-user transaction lock serializes local mutations. Same-key/same-payload
retries return the original receipt; changed arguments yield
`idempotency_conflict`. Persisted receipts survive process restarts. The upstream
GigSim now also stores receipts and serializes freelancer writes, so losing an
HTTP response after commit cannot duplicate a message or debit. Old message
clients without keys remain compatible; the MCP layer always sends a key.

## Reliability, audit, and trust

Every GigSim attempt—including retries—uses a shared Redis sliding-window quota,
20 requests/minute per freelancer by default (configurable up to 50, below its
60/minute limit). Reads and keyed writes have at most three attempts, transport
timeouts, exponential backoff/jitter, and bounded Retry-After waits. Long waits
return a retryable error. No unbounded background loops run in these servers.

Audit entries contain user, tool, masked arguments/results, outcome, and trace ID.
Postgres rejects audit UPDATE/DELETE. Authorization secrets, contact details, and
payment-like numeric strings are masked. Operational request logs are disabled
for MCP containers; corpus/business records retain their actual data. Audit
failure prevents returning an unaudited success; retry with the same key recovers
a committed write receipt. MCP health endpoints are process liveness checks.

The user-scoped MCP client filters tools by role and propagates `X-Trace-ID`.
The Marketplace port uses that client exclusively. A missing server returns
`mcp_unavailable`; upstream failures return structured retryable errors. Durable
graph requeueing and the product's degraded-mode banner remain later milestones.

Trust rationale: Portfolio reads only the assigned synthetic corpus; Marketplace
calls only our authenticated GigSim API; Workspace stores local mock artifacts.
No third-party MCP server is connected at this milestone.

## Contract review and Inspector

`make mcp-snapshot` regenerates snapshots explicitly; review its diff. Tests never
rewrite snapshots. `make mcp-smoke` checks all three authenticated Streamable HTTP
servers, discovery, tool calls, the Scout allowlist, and typed marketplace port.

For MCP Inspector, launch its official UI locally, choose Streamable HTTP, and
connect to each URL listed in the runbook with your bearer token. Capture tools,
a successful read, resource templates, and a proposal dry run with no debit.
Screenshots are manual evidence when browser/Inspector tooling is unavailable;
do not substitute fabricated screenshots. The 40-task tool-design study and
single-agent grounded proposal demo are deferred until retrieval/agents exist.
