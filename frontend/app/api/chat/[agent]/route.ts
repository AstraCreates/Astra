import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ agent: string }> }
) {
  const { agent } = await params;
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
