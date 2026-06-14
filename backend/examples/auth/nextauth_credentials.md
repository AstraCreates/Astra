---
title: NextAuth v5 Email+Password (Credentials) — No OAuth Required
tags: [auth, nextauth, credentials, email, password, next.js]
category: auth
applies_to: [technical, technical_scaffold]
---

# NextAuth v5 Credentials (Email + Password)

Works with zero OAuth setup — only needs NEXTAUTH_SECRET and a DB.

## `frontend/lib/auth.ts`
```typescript
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { getUserByEmail, verifyPassword } from "@/lib/db"; // your DB helpers

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;
        const user = await getUserByEmail(credentials.email as string);
        if (!user) return null;
        const valid = await verifyPassword(credentials.password as string, user.passwordHash);
        if (!valid) return null;
        return { id: user.id, email: user.email, name: user.name };
      },
    }),
  ],
  callbacks: {
    session({ session, token }) {
      if (token.sub) (session.user as { id?: string }).id = token.sub;
      return session;
    },
  },
  session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
  pages: { signIn: "/sign-in", error: "/sign-in" },
  secret: process.env.NEXTAUTH_SECRET ?? "dev-secret",
  trustHost: true,
  useSecureCookies: false, // remove in prod with TLS
});
```

## Sign-in form (client component)
```typescript
"use client";
import { signIn } from "next-auth/react";
import { useState } from "react";
import { useRouter } from "next/navigation";

export function SignInForm() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const result = await signIn("credentials", {
      email: form.get("email"),
      password: form.get("password"),
      redirect: false,
    });
    if (result?.error) {
      setError("Invalid email or password");
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input name="email" type="email" placeholder="Email" required />
      <input name="password" type="password" placeholder="Password" required />
      {error && <p style={{ color: "red" }}>{error}</p>}
      <button type="submit">Sign in</button>
    </form>
  );
}
```

## Sign-up route `app/api/auth/register/route.ts`
```typescript
import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { createUser, getUserByEmail } from "@/lib/db";

export async function POST(req: NextRequest) {
  const { email, password, name } = await req.json();
  if (!email || !password) return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  const existing = await getUserByEmail(email);
  if (existing) return NextResponse.json({ error: "Email already in use" }, { status: 409 });
  const passwordHash = await bcrypt.hash(password, 10);
  const user = await createUser({ email, name, passwordHash });
  return NextResponse.json({ id: user.id, email: user.email }, { status: 201 });
}
```

## Required env vars
```
NEXTAUTH_SECRET=...   # openssl rand -hex 32
DATABASE_URL=...      # Postgres or SQLite
```

## Packages
```json
"next-auth": "^5.0.0-beta.25",
"bcryptjs": "^2.4.3",
"@types/bcryptjs": "^2.4.6"
```

## Notes
- Use this when Google OAuth credentials aren't provisioned — works immediately
- Store passwords with bcrypt (cost factor 10+), never plaintext
- Combine with Supabase or Prisma for the DB helpers
