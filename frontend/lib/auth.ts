import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// Normalize Google email to a stable founder ID — must match backend normalizeSignedInUserId
export function normalizeEmailToFounderId(email: string): string {
  return "google_" + email.toLowerCase().replace(/[^a-z0-9]/g, "_");
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
      // Only non-sensitive scopes so sign-in needs no Google verification.
      // Gmail contact import uses CSV export instead; re-add contacts scopes
      // here (behind incremental auth) if the app is ever HTTPS-verified.
      authorization: {
        params: {
          scope: "openid email profile",
        },
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
      // Persist the Google OAuth access token so we can call the People API.
      if (account?.access_token) {
        token.accessToken = account.access_token;
      }
      // Normalize sub to email-based founder ID so it matches the localStorage identity
      // format used everywhere else in the app.
      const email = (profile as { email?: string } | undefined)?.email ?? (token.email as string | undefined);
      if (email) {
        token.sub = normalizeEmailToFounderId(email);
      }
      return token;
    },
  },
  session: {
    maxAge: 30 * 24 * 60 * 60, // 30 days — used when "Stay signed in" is checked
  },
  pages: {
    signIn: "/",
    error: "/",
  },
  secret: (() => {
    const s = process.env.NEXTAUTH_SECRET;
    if (!s && process.env.NODE_ENV === "production") {
      console.warn("NEXTAUTH_SECRET not set — using dev fallback. Auth will not work.");
    }
    return s ?? "astra-dev-secret-change-in-prod";
  })(),
  trustHost: true,
  // Non-secure cookies only in dev/HTTP. In production TLS is required and
  // NextAuth sets Secure cookies automatically via trustHost.
  useSecureCookies: process.env.NODE_ENV === "production",
});
