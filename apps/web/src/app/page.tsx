import { apiClient } from "../lib/api/client";
export const dynamic = "force-dynamic";

export default async function Home() {
  let available = false;
  try {
    const { data } = await apiClient().GET("/ready", { signal: AbortSignal.timeout(5000), cache: "no-store" });
    available = data?.status === "ok";
  } catch { /* Connection failures are shown in the status panel. */ }
  return <main>
    <header><a className="brand" href="/">gigbid<span>●</span></a><span className="tag">Freelancer copilot</span></header>
    <section className="intro"><p className="eyebrow">YOUR NEXT CHAPTER</p><h1>Good work starts<br />with a better fit.</h1><p className="lede">A place to find opportunities, build proposals from your experience, and keep every decision in your hands.</p></section>
    <section className="status" aria-labelledby="status-title"><div><p className="eyebrow">WORKSPACE STATUS</p><h2 id="status-title">{available ? "Your foundation is ready" : "Connecting to your workspace"}</h2><p role="status"><span className={available ? "dot online" : "dot"} />{available ? "API and storage are available." : "The API or storage is unavailable. Refresh to check again."}</p></div><span className="step">01 / FOUNDATION</span></section>
    <footer><span>GigBid</span><span>Discovery → Evidence → Your approval</span></footer>
  </main>;
}
