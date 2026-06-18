import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

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
          prompt: "select_account",
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
    jwt({ token, account }) {
      // Persist the Google OAuth access token so we can call the People API.
      if (account?.access_token) {
        token.accessToken = account.access_token;
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
  secret: process.env.NEXTAUTH_SECRET ?? "astra-dev-secret-change-in-prod",
  trustHost: true,
  // The app is served over HTTP (no TLS yet). NextAuth otherwise sets `Secure`
  // / `__Secure-`-prefixed cookies behind a proxy, which mobile browsers refuse
  // to store on an insecure origin — so sign-in "just refreshes" and never
  // establishes a session. Force non-secure cookies so HTTP sign-in persists.
  useSecureCookies: false,
});
