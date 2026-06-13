---
title: NextAuth v5 Google OAuth — Working Scaffold
tags: [auth, nextauth, google, next.js, typescript]
category: auth
applies_to: [technical, technical_scaffold]
---

# NextAuth v5 Google OAuth

Exact pattern used in production. Works on HTTP (no TLS required during dev).

## Setup

### `package.json` deps
```json
"next-auth": "^5.0.0-beta.25",
"next": "15.x"
```

### `frontend/lib/auth.ts`
```typescript
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
      authorization: { params: { scope: "openid email profile" } },
    }),
  ],
  callbacks: {
    session({ session, token }) {
      if (session.user && token.sub) {
        (session.user as { id?: string }).id = token.sub;
      }
      return session;
    },
    jwt({ token, account }) {
      if (account?.access_token) token.accessToken = account.access_token;
      return token;
    },
  },
  session: { maxAge: 30 * 24 * 60 * 60 },
  pages: { signIn: "/", error: "/" },
  secret: process.env.NEXTAUTH_SECRET ?? "dev-secret-change-in-prod",
  trustHost: true,
  // CRITICAL: useSecureCookies: false for HTTP deployments (no TLS).
  // Without this, cookies get Secure flag and browsers silently drop them.
  useSecureCookies: false,
});
```

### `frontend/app/api/auth/[...nextauth]/route.ts`
```typescript
import { handlers } from "@/lib/auth";
export const { GET, POST } = handlers;
export const runtime = "nodejs";
```

### `frontend/app/layout.tsx` — wrap with SessionProvider
```typescript
import { SessionProvider } from "next-auth/react";
// ...
export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
```

### Sign in / sign out buttons (client component)
```typescript
"use client";
import { signIn, signOut, useSession } from "next-auth/react";

export function AuthButton() {
  const { data: session } = useSession();
  if (session) {
    return (
      <div>
        <span>{session.user?.email}</span>
        <button onClick={() => signOut({ callbackUrl: "/" })}>Sign out</button>
      </div>
    );
  }
  return (
    <button onClick={() => signIn("google", { callbackUrl: "/dashboard" })}>
      Sign in with Google
    </button>
  );
}
```

### Protecting server components
```typescript
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";

export default async function DashboardPage() {
  const session = await auth();
  if (!session) redirect("/");
  return <div>Welcome {session.user?.email}</div>;
}
```

### Protecting API routes
```typescript
import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export async function GET() {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return NextResponse.json({ user: session.user });
}
```

## Required env vars
```
GOOGLE_CLIENT_ID=...       # from Google Cloud Console → OAuth 2.0 credentials
GOOGLE_CLIENT_SECRET=...   # same
NEXTAUTH_SECRET=...        # openssl rand -hex 32
NEXTAUTH_URL=http://localhost:3000  # or your domain
```

## Google Cloud Console setup
1. Create project → APIs & Services → Credentials → Create OAuth 2.0 Client ID
2. Application type: Web application
3. Authorized redirect URIs: `http://localhost:3000/api/auth/callback/google`
4. Copy Client ID + Secret → env vars

## Critical gotchas
- NEVER use `dynamic = "error"` on pages that call `auth()` — use `force-dynamic` or omit
- NEVER add social buttons without provisioned OAuth credentials — dead buttons break trust
- `useSecureCookies: false` is required for HTTP; remove in prod with TLS
- Do NOT use Clerk — breaks in App Router (headers() conflict, App Router only)
