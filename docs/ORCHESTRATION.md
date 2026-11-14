# Part C: durable orchestration

The hand-written bid graph uses `Send` for Analyst, Risk and Matcher, then joins
all three results once before deciding. Pricing, Writer, Portfolio verification,
Critic and Compliance follow. A Critic may request at most two rewrites. Failure
to pass after that produces `needs_attention`; a policy violation produces
`blocked`. Empty or incompletely verified drafts cannot reach human review.

The conversation graph reads marketplace messages, classifies intent, proposes a
reply and available interview slots, verifies text and applies the same review
gate. Scam signals block the turn. After finishing a turn, the review page can
read new messages in the same graph thread with a new action idempotency key.
Workspace slots are suggestions; this milestone does not automatically book holds.

## Run and review

Run `uv sync --frozen --extra dev`, then `make migrate` and `make dev`.
The Compose migration job initializes both the application schema and the
LangGraph Postgres checkpoint/store tables. `make mcp-bootstrap` provisions the
persona users/credential hashes if not already provisioned. Existing `.env`
tokens and portfolio indexes are preserved. No proposal is sent on startup.

Open `/review` and sign in using the corresponding provisioned `MCP_TOKEN_*`
workspace access key. The browser keeps it in an HttpOnly, SameSite=Strict cookie;
the Next.js server forwards authenticated requests. The key is never stored in
graph state, Redis jobs, browser local storage or audit payloads. This is a minimal
operator login using existing persona credentials, not full product onboarding.

Queue a job ID or conversation ID. Arq picks up the durable work record within
ten seconds. The review page shows status, node progress, checked draft fields,
claim evidence, risk, price rationale, and the marketplace dry-run preview.
Approve sends the exact reviewed payload. Edit rechecks all outgoing text and
requires a new review. Reject requires a reason. A refresh preserves the pending
review, and stale or duplicate decisions return HTTP 409.

All marketplace reads/writes use `MarketplacePort` backed by MCP. Scout can read
the selected job; only the trusted approval executor submits proposals/messages.
Price is an advisory recommendation: the current simulator proposal contract
accepts cover letter, screening answers and skills, rather than a monetary bid.

## Persistence and recovery

Working state, masked append-only execution audit, and long-term memory are
separate. State uses reducers for parallel reports, errors, token counts and step
counts. A thread is scoped by authenticated user and run ID. A unique durable
record deduplicates a normal job/conversation request. Conversation turns reuse
that thread; checkpoint replays fork into a new run.

Checkpoints use `AsyncPostgresSaver` with synchronous durability. A database
outbox stores approval decisions before worker execution. The worker reconciles
queued/running records after restarts, honors retry delays, and takes a Postgres
transaction advisory lock before executing a run. The exact payload fingerprint,
idempotency key, user, tool and expiry bind an approval grant. MCP and simulator
receipts retain the result of an external action across response loss or crashes.

The UI exposes checkpoint history and replay. A replay clears authorization and
uses a fresh run/write key; replaying a send or approval returns to verification
and human review. Restarting a completed worker task recovers its terminal state
without generating another proposal. Retryable outages and 429/5xx failures enter
`retry_wait`, then retry with bounded backoff; exhausted failures become visible
dead letters. Budget exhaustion becomes `needs_attention`.

`agent/config.yaml` routes every model node, sets two node attempts, five worker
attempts, a 30-step budget, a 48,000-token budget and a 30-minute approval lifetime.
The existing local `qwen2.5:3b` serves every role; no model is downloaded. The
configured fallback is used for cheap nodes when it differs from their primary
route. A distinct fallback model must already be installed and configured to
provide model redundancy; the default installation has one model.

Policies remain in `data/policy_pack/rules.md`, with a configurable machine-checked
subset in `enforcement.yaml`. Matching contact/guarantee patterns block even if
the model passes them. Injection/off-platform job patterns impose a risk floor.
A policy fingerprint change after review prevents sending under an old verdict.

## Memory promotion

LangGraph Postgres Store keeps tenant-separated `style` and `outcome` namespaces.
Exact whole-sentence deletions become style preferences only after appearing in
three distinct edited, approved and successfully sent threads. Retry/replay of
the same observation does not increase its count. PII-containing deletions are
not promoted. Observation records are kept separately from promoted knowledge.

Outcome promotion requires an actually sent proposal and a matching marketplace
client-history status for the same job/persona. Only replied, interview, hired
and no_reply statuses qualify; pending submissions never count as ignored.
The review page loads and deletes both memory types. Deleting a style item also
removes its supporting observations.

## Verification

`make graph-diagrams` produces Mermaid sources from both compiled graphs in
`docs/graphs/`. `make graph-test` runs deterministic orchestration tests. Set
`GRAPH_TEST_DATABASE_URL` to enable the Postgres test; it creates/removes its own
schema and uses an isolated simulator with deterministic model outputs. It tests
restart/resume, concurrent workers, exact approval binding, tenant isolation,
one proposal/Connects spend, outbox recovery and safe checkpoint replay.

The unit suite covers joins, revision bounds, edits requiring another approval,
rejection, policy blocks, budget exhaustion, empty verified drafts, conversation
turns, memory promotion and configured model fallback. These are correctness
tests, not measured model quality or reply-rate evidence. The 50-job ReAct /
supervisor / hand-built comparison is explicitly deferred for this session.

## Diagnosing skipped and incomplete jobs

Risk findings now require exact quotes from the job or public client history.
The configured risk levels derive the score; a model no longer invents a high
numeric risk while reporting no red flags. Client payment/hiring checks and
policy risk floors remain enforced. Decision reasons include the actual score
and cutoff. Existing skipped runs keep their original decisions and traces.

Matcher output uses short, decoder-constrained E1/E2 source IDs, mapped back to
the real owned chunk IDs after validation. Similarity scores are kept out of the
matcher prompt so they are not mistaken for requirement coverage. Every matcher
report must include a requirement matrix. Writer output is bounded and requires
exactly the posted screening questions; questions cannot silently disappear.

The CPU verifier has a per-request time budget. Short drafts reduce the number
of factual sentences it must grade. Incomplete verification may return to Writer
within the same total two-revision allowance; every rewritten field is verified
again before review. User edits and conversation replies never bypass incomplete
verification. Exhausted verification, unsupported citations and malformed model
output show `needs_attention`, with sentence diagnostics retained in run state.
Infrastructure outages still retry and can eventually become dead letters.

When the verifier leaves part of a factual sentence unchecked, it may retry once
with the whole original sentence fixed by the decoding schema. The retry must
grade every assertion and still passes the existing source/citation/numeric
checks. It cannot fill in missing words or accept partially supported claims.
Simple future estimates such as "I aim to deliver an initial model in two weeks"
are intentions, while embedded past-experience assertions still require evidence.
New replay runs reset their revision allowance; original checkpoints stay intact.

Compliance also returns source-quoted findings instead of an ungrounded pass/fail
verdict. Verified past performance metrics and availability statements are not
contact details or guaranteed future business outcomes. The deterministic policy
checks still run first. Replaying Critic/Compliance/send stages returns through
verification, and the executor refuses any outgoing field that differs from its
verified text, even when the surrounding approval hash matches.

For a failed run, use **Redraft safely in a new run** or **Retry analysis in a new
run**. These use checkpoint replay, preserve the original trace, and clear all
approval state. A retried run still needs explicit human approval before sending.
