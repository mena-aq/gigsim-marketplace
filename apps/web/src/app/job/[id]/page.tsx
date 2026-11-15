"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import createClient from "openapi-fetch";
import type { paths } from "../../../lib/api/schema";

const client = createClient<paths>({ baseUrl: "/api" });
type Job = { id: string; title: string; description: string; skills: string[]; budget_min?: number | null; budget_max?: number | null; timeline_days?: number | null; screening_questions?: string[]; category?: string | null; status: string };

export default function JobDetail() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`/api/agent/jobs/${encodeURIComponent(params.id)}`, { cache: "no-store" }).then(async response => {
      const found = response.ok ? await response.json() as Job : null;
      if (!active) return;
      if (response.status === 401) setError("Choose a persona before opening a job.");
      else if (response.status === 503) setError("Marketplace unavailable — you can still queue this job once it is back, and work already queued will resume automatically.");
      else if (!response.ok || !found) setError("This job is not available.");
      else setJob(found);
    }).catch(() => { if (active) setError("Workspace unavailable — work is queued"); });
    return () => { active = false; };
  }, [params.id]);

  async function analyze() {
    setBusy(true); setError("");
    const result = await client.POST("/agent/runs", { body: { kind: "bid", target: params.id } });
    if (result.error || !result.data) { setError("Could not queue this job"); setBusy(false); return; }
    router.push(`/review?run=${encodeURIComponent(result.data.id)}`);
  }

  return <main>
    <header><Link className="brand" href="/review">gigbid<span>●</span></Link><span className="tag">Job detail</span></header>
    <p><Link href="/review">← Back to job inbox</Link></p>
    {error && <p role="alert" className="alert">{error}</p>}
    {!job && !error ? <section className="panel"><p>Loading job…</p></section> : job && <>
      <section className="panel job-detail"><p className="eyebrow">GIGSIM JOB</p><h1>{job.title}</h1><p className="job-description">{job.description}</p><p><strong>Skills:</strong> {job.skills.join(" · ")}</p><p><strong>Budget:</strong> {job.budget_max ? `$${job.budget_min ?? 0}–$${job.budget_max}` : "Not specified"}{job.timeline_days ? ` · ${job.timeline_days} days` : ""}</p>{job.screening_questions?.length ? <><h2>Screening questions</h2><ul>{job.screening_questions.map(question => <li key={question}>{question}</li>)}</ul></> : null}<button disabled={busy} onClick={() => void analyze()}>{busy ? "Queueing…" : "Analyze this job"}</button></section>
    </>}
  </main>;
}
