import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
      authorization: {
        params: {
          scope:
            "openid email profile " +
            "https://www.googleapis.com/auth/contacts.readonly " +
            "https://www.googleapis.com/auth/contacts.other.readonly",
          access_type: "offline",
          prompt: "consent",
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
  pages: {
    signIn: "/",
    error: "/",
  },
  secret: process.env.NEXTAUTH_SECRET ?? "astra-dev-secret-change-in-prod",
  trustHost: true,
});
