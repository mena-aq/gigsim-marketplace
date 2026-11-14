"use client";

import { useState } from "react";

const personas = [
  { id: "ml_engineer", name: "AI / ML Engineer", detail: "Models, forecasting, and applied machine learning" },
  { id: "fullstack_dev", name: "Full-stack Developer", detail: "Web apps, APIs, and product engineering" },
  { id: "data_analyst", name: "Data Analyst", detail: "Analytics, dashboards, and decision support" },
];

export default function Home() {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function choose(persona: string) {
    setBusy(persona); setError("");
    try {
      const response = await fetch("/api/agent/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona }) });
      if (!response.ok) throw new Error("That persona is not available. Check the workspace configuration.");
      window.location.href = "/review";
    } catch (e) { setError(e instanceof Error ? e.message : "Workspace unavailable"); setBusy(""); }
  }
  return <main>
    <header><a className="brand" href="/">gigbid<span>●</span></a><span className="tag">GigSim demo</span></header>
    <section className="intro"><p className="eyebrow">CHOOSE A FREELANCER</p><h1>Find the next<br />good fit.</h1><p className="lede">Pick a provided persona to browse their existing GigSim jobs and review proposals grounded in their portfolio.</p></section>
    {error && <p role="alert" className="alert">{error}</p>}
    <section className="persona-grid" aria-label="Personas">
      {personas.map(persona => <button className="persona-card" key={persona.id} onClick={() => void choose(persona.id)} disabled={Boolean(busy)}>
        <span className="persona-name">{persona.name}</span><span className="persona-detail">{persona.detail}</span><span className="persona-action">{busy === persona.id ? "Opening…" : "Open workspace →"}</span>
      </button>)}
    </section>
    <footer><span>GigBid</span><span>Discovery → Evidence → Your approval</span></footer>
  </main>;
}
