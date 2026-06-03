import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const providers = [];

// Only add Google if credentials are configured
if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) {
  providers.push(
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    })
  );
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  basePath: "/api/auth",
  providers,
  callbacks: {
    session({ session, token }) {
      if (session.user && token.sub) {
        (session.user as { id?: string }).id = token.sub;
      }
      return session;
    },
    jwt({ token }) {
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
