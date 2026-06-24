import { getToken } from "next-auth/jwt";
import { NextRequest } from "next/server";

export const runtime = "nodejs";

// Returns the raw HS256-signed session JWT so the client can send it
// as Authorization: Bearer to the backend for verified identity.
// Only accessible to the authenticated session owner (cookie-bound).
export async function GET(req: NextRequest) {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    return Response.json({ error: "Auth not configured" }, { status: 503 });
  }
  const token = await getToken({ req, secret, raw: true });
  if (!token) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  return Response.json({ token });
}
