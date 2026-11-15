import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const jar = await cookies();
  const upstream = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  if (!["GET", "HEAD"].includes(request.method)) {
    const origin = request.headers.get("origin");
    const host = (request.headers.get("x-forwarded-host") ?? request.headers.get("host"))?.split(",")[0].trim();
    const allowed = host ? [`http://${host}`, `https://${host}`] : [];
    if (origin && !allowed.includes(origin)) return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  }
  if (path.join("/") === "session" && request.method === "POST") {
    const body = await request.json();
    const personaTokens: Record<string, string | undefined> = {
      ml_engineer: process.env.MCP_TOKEN_ML_ENGINEER,
      fullstack_dev: process.env.MCP_TOKEN_FULLSTACK_DEV,
      data_analyst: process.env.MCP_TOKEN_DATA_ANALYST,
    };
    const token = typeof body?.persona === "string" ? personaTokens[body.persona] : body?.token;
    if (typeof token !== "string" || token.length < 1 || token.length > 512) return NextResponse.json({ detail: "Enter your access key" }, { status: 400 });
    try {
      const check = await fetch(upstream + "/agent/me", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (!check.ok) return NextResponse.json({ detail: "Access key was not accepted" }, { status: 401 });
      jar.set("gigbid_session", token, { httpOnly: true, sameSite: "strict", secure: request.nextUrl.protocol === "https:", path: "/", maxAge: 28800 });
      return NextResponse.json(await check.json());
    } catch { return NextResponse.json({ detail: "Workspace unavailable" }, { status: 503 }); }
  }
  if (path.join("/") === "session" && request.method === "DELETE") {
    jar.delete("gigbid_session");
    return new NextResponse(null, { status: 204 });
  }
  const token = jar.get("gigbid_session")?.value;
  if (!token) return NextResponse.json({ detail: "Sign in to your workspace" }, { status: 401 });
  try {
    const response = await fetch(upstream + "/agent/" + path.map(encodeURIComponent).join("/") + request.nextUrl.search, {
      method: request.method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(), cache: "no-store", signal: request.signal,
    });
    return new NextResponse(response.body, { status: response.status, headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json", "Cache-Control": "no-store", "X-Accel-Buffering": "no" } });
  } catch { return NextResponse.json({ detail: "Workspace unavailable — work is queued" }, { status: 503 }); }
}

export { proxy as GET, proxy as POST, proxy as DELETE };
