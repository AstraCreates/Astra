import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { SignJWT, jwtVerify } from "jose";

function _secretKey(secret: string | string[]): Uint8Array {
  return new TextEncoder().encode(Array.isArray(secret) ? secret[0] : secret);
}

// Normalize Google email to a stable founder ID — must match backend normalizeSignedInUserId
function _normalizeEmail(email: string): string {
  return "google_" + email.toLowerCase().replace(/[^a-z0-9]/g, "_");
}

const _secret = (() => {
  const s = process.env.NEXTAUTH_SECRET;
  if (!s && process.env.NODE_ENV === "production") {
    throw new Error("NEXTAUTH_SECRET must be set in production");
  }
  return s ?? "astra-dev-secret-change-in-prod";
})();

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
      authorization: {
        params: { scope: "openid email profile" },
      },
    }),
  ],
  callbacks: {
    session({ session, token }) {
      if (session.user && token.sub) {
        (session.user as { id?: string }).id = token.sub;
      }
      (session as { accessToken?: string }).accessToken = token.accessToken as string | undefined;
      return session;
    },
    jwt({ token, account, profile }) {
      if (account?.access_token) {
        token.accessToken = account.access_token;
      }
      // Normalize sub to email-based founder ID so JWT identity matches localStorage identity
      const email = (profile as { email?: string } | undefined)?.email ?? (token.email as string | undefined);
      if (email) {
        token.sub = _normalizeEmail(email);
      }
      return token;
    },
  },
  // Use plain HS256 JWS (not encrypted JWE) so the backend can verify with PyJWT
  jwt: {
    encode: async ({ token, secret }) => {
      const key = _secretKey(secret as string | string[]);
      return new SignJWT(token as Record<string, unknown>)
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt()
        .setExpirationTime("30d")
        .sign(key);
    },
    decode: async ({ token, secret }) => {
      if (!token) return null;
      try {
        const { payload } = await jwtVerify(token, _secretKey(secret as string | string[]));
        return payload as Parameters<NonNullable<Parameters<typeof NextAuth>[0]["jwt"]>["decode"]>[0] extends { token?: infer T } ? Awaited<T> : never;
      } catch {
        return null;
      }
    },
  },
  session: {
    maxAge: 30 * 24 * 60 * 60,
  },
  pages: {
    signIn: "/",
    error: "/",
  },
  secret: _secret,
  trustHost: true,
  useSecureCookies: process.env.NODE_ENV === "production",
});
