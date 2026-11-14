"use client";

import "./review.css";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import createClient from "openapi-fetch";
import type { paths, components } from "../../lib/api/schema";

const client = createClient<paths>({ baseUrl: "/api" });
type Detail = components["schemas"]["RunDetail"];
type Json = Record<string, any>;
type Job = { id: string; title: string; description: string; skills: string[]; budget_min?: number | null; budget_max?: number | null; timeline_days?: number | null; screening_questions?: string[]; category?: string | null; status: string };

export default function Review() {
  const [signedIn, setSignedIn] = useState(false);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [body, setBody] = useState("");
  const [answers, setAnswers] = useState<Json[]>([]);
  const [reason, setReason] = useState("");
  const [events, setEvents] = useState<Json[]>([]);
  const [memory, setMemory] = useState<Json[]>([]);
  const [history, setHistory] = useState<Json[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobQuery, setJobQuery] = useState("");
  const [why, setWhy] = useState<Json | null>(null);
  const [retired, setRetired] = useState<string[]>([]);
  const [submission, setSubmission] = useState<Json | null>(null);
  const [recentEdits, setRecentEdits] = useState<Json | null>(null);
  useEffect(() => {
    const run = new URLSearchParams(window.location.search).get("run");
    if (run) setSelected(run);
  }, []);
  useEffect(() => {
    if (selected) window.history.replaceState(null, "", `/review?run=${encodeURIComponent(selected)}`);
  }, [selected]);
  const loadJobs = useCallback(async (query = "") => {
    const result = await client.GET("/agent/jobs", { params: { query: { q: query || undefined } } });
    if (result.response.status === 401) { setSignedIn(false); return; }
    if (result.error) throw new Error("Job inbox is temporarily unavailable — try again shortly");
    setJobs(((result.data as { items?: Job[] } | undefined)?.items ?? []));
  }, []);
  const refresh = useCallback(async () => {
    const result = await client.GET("/agent/runs");
    if (result.response.status === 401) { setSignedIn(false); return; }
    if (result.error) throw new Error("Workspace unavailable — work is queued");
    setSignedIn(true);
    if (selected) {
      const next = await client.GET("/agent/runs/{run_id}", { params: { path: { run_id: selected } } });
      if (next.error) throw new Error("Run details unavailable");
      setDetail(next.data ?? null);
    }
  }, [selected]);
  useEffect(() => {
    const check = () => refresh().catch(e => setError(e.message));
    check();
    const timer = setInterval(check, 4000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    loadJobs().catch(e => setError(e.message));
  }, [loadJobs]);
  const review = detail?.review as Json | null;
  const state = (detail?.state ?? {}) as Json;
  useEffect(() => {
    setBody(review?.draft?.cover_letter ?? ""); setAnswers(review?.draft?.screening_answers ?? []); setReason("");
  }, [review?.review_hash]);
  useEffect(() => {
    setEvents([]); setHistory([]);
    if (!selected || !signedIn) return;
    const stream = new EventSource(`/api/agent/runs/${encodeURIComponent(selected)}/events`);
    stream.onmessage = event => setEvents(old => [...old.slice(-99), JSON.parse(event.data)]);
    return () => stream.close();
  }, [selected, signedIn]);
  const decisionKey = state.decision?.action ?? "";
  useEffect(() => {
    setWhy(null);
    if (!selected || !signedIn || !decisionKey) return;
    fetch(`/api/agent/runs/${encodeURIComponent(selected)}/decision`).then(r => r.ok ? r.json() : null).then(setWhy).catch(() => setWhy(null));
  }, [selected, signedIn, decisionKey]);
  const loadRetired = useCallback(async () => {
    const r = await fetch("/api/agent/evidence/retired");
    if (r.ok) setRetired(await r.json());
  }, []);
  useEffect(() => { if (signedIn) void loadRetired(); }, [signedIn, loadRetired]);
  async function changeEvidence(itemId: string, restore: boolean) {
    const path = itemId.split("/").map(encodeURIComponent).join("/");
    const r = await fetch(restore ? `/api/agent/evidence/restore/${path}` : `/api/agent/evidence/${path}`, { method: restore ? "POST" : "DELETE" });
    if (!r.ok) throw new Error("Could not change this evidence item");
    await loadRetired();
  }
  async function regenerate() {
    const historyResult = await client.GET("/agent/runs/{run_id}/history", { params: { path: { run_id: selected } } });
    const checkpoint = historyResult.data?.[0] as Json | undefined;
    if (!checkpoint?.checkpoint_id) throw new Error("No checkpoint is available to regenerate from");
    const result = await client.POST("/agent/runs/{run_id}/replay", { params: { path: { run_id: selected } }, body: { checkpoint_id: checkpoint.checkpoint_id, node: "scout" } });
    if (result.error || !result.data) throw new Error("Could not queue a regeneration");
    setSelected(result.data.id); setDetail(null);
  }
  const detailStatus = detail?.status ?? "";
  useEffect(() => {
    setSubmission(null);
    if (!selected || !signedIn || !["queued", "running", "retry_wait", "sent", "dead_letter", "needs_attention"].includes(detailStatus)) return;
    fetch(`/api/agent/runs/${encodeURIComponent(selected)}/submission`).then(r => r.ok ? r.json() : null).then(data => setSubmission(data?.idempotency_key ? data : null)).catch(() => setSubmission(null));
  }, [selected, signedIn, detailStatus]);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); } finally { setBusy(false); }
  }
  async function approve(action: "approve" | "edit" | "reject") {
    if (!review || !selected) return;
    const result = await client.POST("/agent/runs/{run_id}/approval", { params: { path: { run_id: selected } }, body: {
      action, review_hash: review.review_hash, reason,
      ...(action === "edit" ? { cover_letter: body, screening_answers: answers as components["schemas"]["ScreeningAnswer"][] } : {}),
    } });
    if (result.error) throw new Error("Review changed or request was rejected. Refresh and try again.");
    setDetail(null);
  }
  const jobCards = jobs.map(job => <article className="job-card" key={job.id}>
    <div><h3>{job.title}</h3><p>{job.description.slice(0, 220)}{job.description.length > 220 ? "…" : ""}</p>
      <small>{job.skills?.join(" · ")}{job.budget_max ? ` · $${job.budget_min ?? 0}–$${job.budget_max}` : ""}{job.timeline_days ? ` · ${job.timeline_days} days` : ""}</small>
    </div><Link className="job-action" href={`/job/${encodeURIComponent(job.id)}`}>Analyze</Link>
  </article>);
  return <main>
    <header><a className="brand" href="/">gigbid<span>●</span></a><h1 className="review-title">Review workspace</h1></header>
    <p>Review evidence, edit drafts, and choose what leaves your workspace.</p>
    {error && <p role="alert" className="alert">{error}</p>}
    {!signedIn ? <section className="panel"><p>Your workspace session is not active.</p><a href="/">Choose a persona</a></section> : <>
      <button onClick={() => void act(async () => { await fetch("/api/agent/session", { method: "DELETE" }); setSignedIn(false); setDetail(null); setSelected(""); })}>Sign out</button>
      <section className="analytics-strip" aria-label="Demo analytics"><div><span>DEMO ANALYTICS</span><strong>12</strong><small>jobs reviewed</small></div><div><span>PROPOSALS</span><strong>4</strong><small>sent with approval</small></div><div><span>REPLY RATE</span><strong>25%</strong><small>simulated history</small></div><div><span>CONNECTS</span><strong>28</strong><small>spent this week</small></div></section>
      <section className="panel inbox"><div className="inbox-heading"><div><p className="eyebrow">JOB INBOX</p><h2>Open GigSim jobs</h2></div><form onSubmit={e => { e.preventDefault(); void loadJobs(jobQuery).catch(err => setError(err.message)); }}><label className="sr-only" htmlFor="job-search">Search jobs</label><input id="job-search" placeholder="Search jobs" value={jobQuery} onChange={e => setJobQuery(e.target.value)} /></form></div>{jobs.length === 0 ? <p>No jobs found.</p> : <div className="job-list">{jobCards}</div>}</section>
      <section className="panel" aria-live="polite">{!detail ? <p>{selected ? "Loading run…" : "Choose Analyze on a job to begin."}</p> : <>
          <h2>{state.job?.title ?? detail.target}</h2><p><strong>{detail.status.replaceAll("_", " ")}</strong> · {state.steps ?? 0} steps · {state.tokens ?? 0} tokens</p>
          {detail.status === "retry_wait" && <p role="status" className="alert">A dependency is unavailable or rate limited — work is queued for retry.</p>}
          {(detail.error || Object.keys(state.errors ?? {}).length > 0) && <pre>{JSON.stringify(detail.error ?? state.errors, null, 2)}</pre>}
          {["needs_attention", "dead_letter"].includes(detail.status) && <button disabled={busy} onClick={() => void act(async () => {
            const historyResult = await client.GET("/agent/runs/{run_id}/history", { params: { path: { run_id: selected } } });
            const checkpoint = historyResult.data?.[0] as Json | undefined;
            if (!checkpoint?.checkpoint_id) throw new Error("No checkpoint is available to retry");
            const node = detail.kind === "bid" ? (state.draft ? "writer" : "scout") : (state.messages ? "liaison" : "read_messages");
            const result = await client.POST("/agent/runs/{run_id}/replay", { params: { path: { run_id: selected } }, body: { checkpoint_id: checkpoint.checkpoint_id, node } });
            if (result.error || !result.data) throw new Error("Could not queue a safe retry");
            setSelected(result.data.id); setDetail(null);
          })}>{state.draft ? "Redraft safely in a new run" : "Retry analysis in a new run"}</button>}
          {submission && <section className="submission panel"><h3>Submission</h3>
            <table><tbody>
              <tr><td>Status</td><td><strong>{submission.status.replaceAll("_", " ")}</strong> (worker attempts since approval: {submission.worker_attempts})</td></tr>
              <tr><td>Approved at</td><td>{submission.approved_at ?? "–"}</td></tr>
              <tr><td>Idempotency key</td><td><code>{submission.idempotency_key}</code></td></tr>
              <tr><td>Send receipts for this key</td><td><strong>{submission.receipts.length}</strong> (database allows at most 1)</td></tr>
              <tr><td>Send calls logged</td><td>{submission.send_calls_logged}</td></tr>
              <tr><td>Approval grant</td><td>{submission.grants.length ? (submission.grants.some((g: Json) => g.consumed) ? "consumed" : "issued, not yet consumed") : "none"}</td></tr>
              {submission.result && <tr><td>Marketplace result</td><td><code>{JSON.stringify(submission.result)}</code></td></tr>}
            </tbody></table>
            <p><small>If the worker crashes after approval, it restarts the run with the same key; the receipt lookup returns the stored result instead of sending again.</small></p>
          </section>}
          {state.decision && <p>{state.decision.action}: {state.decision.reason}</p>}
          {why?.decision && <details open={why.decision.action !== "bid"} className="why"><summary>Why this decision</summary>
            <p><strong>{why.decision.action.toUpperCase()}</strong> — {why.decision.reason}</p>
            <table><thead><tr><th>Check</th><th>Score</th><th>Threshold</th><th>Result</th></tr></thead><tbody>
              <tr className={why.driver === "risk" ? "driver" : ""}><td>Risk (node <code>risk</code>)</td><td>{why.risk.score?.toFixed(2) ?? "–"}</td><td>skip at ≥ {why.risk.maximum.toFixed(2)}</td><td>{why.risk.score >= why.risk.maximum ? "SKIP" : "pass"}</td></tr>
              <tr className={why.driver === "fit" ? "driver" : ""}><td>Fit (node <code>matcher</code>)</td><td>{why.fit.score?.toFixed(2) ?? "–"}</td><td>watch below {why.fit.minimum.toFixed(2)}</td><td>{why.fit.score < why.fit.minimum ? "WATCH" : "pass"}</td></tr>
            </tbody></table>
            {why.risk.flags?.length > 0 && <p>Risk flags: {why.risk.flags.join("; ")}</p>}
            {why.risk.explanation && <p>Risk explanation: {why.risk.explanation}</p>}
            {why.fit.missing_skills?.length > 0 && <p>Missing skills: {why.fit.missing_skills.join(", ")}</p>}
            <p><small>The <code>decision</code> node is deterministic (no model call): it compares the <code>risk</code> and <code>matcher</code> scores to <code>agent/config.yaml</code> thresholds. If the skip was wrong, the wrong score came from the node highlighted above.</small></p>
            <ol className="timeline">{why.nodes.map((n: Json, i: number) => <li key={i} className={n.node === (why.driver === "risk" ? "risk" : why.driver === "fit" ? "matcher" : "decision") ? "driver" : ""}>{n.node}{n.seconds ? ` · ${n.seconds.toFixed(1)}s` : ""}{n.error ? ` · error: ${n.error}` : ""}<small> {n.update_keys.join(", ")}</small></li>)}</ol>
          </details>}
          {state.compliance?.violations?.length > 0 && <p role="alert">Blocked: {state.compliance.violations.join("; ")}</p>}
          {review && <>
            <h3>Proposal or reply</h3><label>Draft<textarea rows={10} value={body} onChange={e => setBody(e.target.value)} /></label>
            {answers.map((answer, index) => <label key={index}>{answer.question}<textarea value={answer.answer} onChange={e => setAnswers(old => old.map((item, i) => i === index ? { ...item, answer: e.target.value } : item))} /></label>)}
            <h3>Price and Connects</h3><p>{review.price?.amount ? `Recommended price: $${review.price.amount}. ` : ""}{review.price?.rationale}</p><p>Connects cost: {review.preview?.connects_cost ?? 0}</p>
            <section className="claims"><h3>Claims and the evidence behind them</h3>
              {Object.entries((review.verification ?? {}) as Json).map(([field, report]: [string, Json]) => <div key={field}>
                <h4>{field === "cover_letter" ? "Cover letter" : `Screening answer ${Number(field) + 1}`}</h4>
                {(report.sentences ?? []).map((sentence: Json, i: number) => <div key={i} className={sentence.kept ? "claim kept" : "claim removed"}>
                  <p>{sentence.kept ? "✔" : "✘ removed from draft"} {sentence.text}</p>
                  {sentence.claims.map((claim: Json, j: number) => <div key={j} className="claim-row">
                    <small>{claim.kind} · <strong>{claim.status.replaceAll("_", " ")}</strong> — {claim.reason}</small>
                    {claim.evidence_ids.map((id: string) => { const ev = (review.evidence ?? []).find((e: Json) => e.chunk_id === id); return <details key={id}><summary>Evidence: {ev?.source ?? "unavailable (deleted)"}</summary>
                      {ev && <><blockquote>{ev.text}</blockquote><button disabled={busy} onClick={() => void act(() => changeEvidence(ev.id, false))}>Delete this evidence</button></>}
                    </details>; })}
                    {claim.kind === "experience" && claim.evidence_ids.length === 0 && <small> — no evidence cited</small>}
                  </div>)}
                </div>)}
              </div>)}
              {retired.length > 0 && <div><h4>Deleted evidence</h4><ul>{retired.map(id => <li key={id}>{id} <button disabled={busy} onClick={() => void act(() => changeEvidence(id, true))}>Restore</button></li>)}</ul></div>}
              <button disabled={busy} onClick={() => void act(regenerate)}>Regenerate with current evidence</button>
              <p><small>Deleted evidence is excluded from retrieval and verification. Regenerating re-runs the analysis, so claims that depended on it are dropped or rewritten, and this draft can no longer be approved against it.</small></p>
            </section>
            <details><summary>Risk report and evidence</summary><pre>{JSON.stringify({ risk: review.risk, evidence: review.evidence, verification: review.verification, critique: review.critique }, null, 2)}</pre></details>
            <details><summary>Exact marketplace preview</summary><pre>{JSON.stringify(review.preview, null, 2)}</pre></details>
            <label>Reason or edit note<input value={reason} onChange={e => setReason(e.target.value)} /></label>
            <div className="actions"><button disabled={busy || body !== review.draft.cover_letter || JSON.stringify(answers) !== JSON.stringify(review.draft.screening_answers ?? [])} onClick={() => void act(() => approve("approve"))}>Approve and send</button><button disabled={busy || !body.trim()} onClick={() => void act(() => approve("edit"))}>Save edits and recheck</button><button disabled={busy || !reason.trim()} onClick={() => void act(() => approve("reject"))}>Reject</button></div>
            <p><small>Edits return for review after verification and compliance checks.</small></p>
          </>}
          <details><summary>Run state and trace ({detail.trace_id})</summary><pre>{JSON.stringify(state, null, 2)}</pre></details>
          <h3>Live progress</h3><ol>{events.filter(event => event.action.startsWith("node.") || event.action.startsWith("human.")).map(event => <li key={event.id}>{event.action}<small> {event.payload.seconds ? `${event.payload.seconds.toFixed(1)}s` : ""}</small></li>)}</ol>
          {detail.status === "sent" && detail.kind === "bid" && <button disabled={busy} onClick={() => void act(async () => { const result = await client.POST("/agent/runs/{run_id}/outcome", { params: { path: { run_id: selected } } }); if (result.error) throw new Error("Marketplace outcome is not available yet"); })}>Refresh confirmed outcome memory</button>}
          {detail.kind === "conversation" && ["sent", "rejected", "blocked"].includes(detail.status) && <button disabled={busy} onClick={() => void act(async () => { const result = await client.POST("/agent/runs/{run_id}/continue", { params: { path: { run_id: selected } } }); if (result.error) throw new Error("Could not queue the next conversation turn"); })}>Read new messages and draft next reply</button>}
          <details><summary>Checkpoint history and replay</summary><button disabled={busy} onClick={() => void act(async () => {
            const result = await client.GET("/agent/runs/{run_id}/history", { params: { path: { run_id: selected } } });
            if (result.error) throw new Error("Checkpoint history unavailable"); setHistory(result.data ?? []);
          })}>Load checkpoints</button>{history.map(checkpoint => <div key={checkpoint.checkpoint_id}><p>{checkpoint.created_at} · Next: {checkpoint.next.join(", ") || "finished"}</p><button disabled={busy} onClick={() => void act(async () => {
            const result = await client.POST("/agent/runs/{run_id}/replay", { params: { path: { run_id: selected } }, body: { checkpoint_id: checkpoint.checkpoint_id, node: checkpoint.next[0] ?? "execute" } });
            if (result.error || !result.data) throw new Error("Could not replay this checkpoint"); setSelected(result.data.id); setDetail(null);
          })}>Replay in a new run</button></div>)}<p><small>Replaying a send returns to verification and human review.</small></p></details>
        </>}</section>
      <section className="panel"><h2>Learned memory</h2><button disabled={busy} onClick={() => void act(async () => {
        const result = await client.GET("/agent/memory/{kind}", { params: { path: { kind: "style" } } });
        const outcomes = await client.GET("/agent/memory/{kind}", { params: { path: { kind: "outcome" } } });
        setMemory([...(result.data ?? []).map(item => ({ ...item, kind: "style" })), ...(outcomes.data ?? []).map(item => ({ ...item, kind: "outcome" }))]);
        const recent = await fetch("/api/agent/memory/style/recent");
        setRecentEdits(recent.ok ? await recent.json() : null);
      })}>Load memory</button>
      {recentEdits && <div className="recent-edits"><h3>Last five edits it observed</h3><p><small>{recentEdits.rule} {recentEdits.note}</small></p>
        {recentEdits.edits.length === 0 ? <p>No deleted sentences observed yet.</p> : <ol>{recentEdits.edits.map((edit: Json) => <li key={edit.key + edit.run_id}>
          <q>{edit.removed_sentence}</q><br />
          <small>{edit.promoted ? "Promoted to a style rule" : `Not promoted yet — seen in ${edit.seen_in_proposals} of ${recentEdits.threshold} proposals`}</small>
        </li>)}</ol>}</div>}
      {memory.map(item => <div key={item.kind + item.key} className="memory-item">
        {item.kind === "style" ? <p><strong>Style rule:</strong> avoid “{item.value.avoid_sentence}”<br /><small>{item.value.rule} · seen {item.value.count} times</small></p> : <pre>{JSON.stringify(item.value, null, 2)}</pre>}
        <button onClick={() => void act(async () => { await client.DELETE("/agent/memory/{kind}/{key}", { params: { path: { kind: item.kind, key: item.key } } }); setMemory(old => old.filter(value => value !== item)); setRecentEdits(null); })}>Delete memory</button></div>)}</section>
    </>}
  </main>;
}
