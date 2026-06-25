import { auth } from "@/lib/auth";
import { normalizeEmailToFounderId } from "@/lib/auth";
import { SignJWT } from "jose";

export const runtime = "nodejs";

// Returns a short-lived HS256 JWT signed with NEXTAUTH_SECRET.
// The backend verifies it with ASTRA_JWT_SECRET (same value).
// Only callable from the authenticated session owner — auth() is cookie-bound, server-side.
export async function GET() {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    return Response.json({ error: "Auth not configured" }, { status: 503 });
  }

  const session = await auth();
  if (!session?.user?.email) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const sub = normalizeEmailToFounderId(session.user.email);
  const key = new TextEncoder().encode(secret);

  const token = await new SignJWT({ sub, email: session.user.email })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("2h")
    .sign(key);

  return Response.json({ token });
}
