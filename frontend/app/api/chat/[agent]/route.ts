import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const AGENT_ALLOWLIST = /^[a-z_]{1,64}$/;

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ agent: string }> }
) {
  const { agent } = await params;
  if (!AGENT_ALLOWLIST.test(agent)) {
    return NextResponse.json({ error: "Invalid agent" }, { status: 400 });
  }

  const body = await req.json();
  const userId = req.headers.get("x-astra-user-id") ?? "";
  const headers = new Headers({ "Content-Type": "application/json" });
  if (userId) headers.set("x-astra-user-id", userId);

  const res = await fetch(`${BACKEND}/chat/${agent}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
