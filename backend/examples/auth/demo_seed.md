---
title: Demo Account Seed for Preview Deploys (No Real DB)
tags: [auth, demo, preview, seed, nextauth]
category: auth
applies_to: [technical, technical_scaffold]
---

# Demo Account Seed for Preview Deploys (No Real DB)

Lets preview/staging deploys work when `DATABASE_URL` is a placeholder.
`authorize()` tries the real DB first; if that throws or returns nothing, it falls back to hardcoded demo credentials.
No migrations needed — works on Vercel preview branches out of the box.

## `lib/auth.ts` — authorize() with demo fallback
```typescript
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";

const DEMO_EMAIL = "demo@demo.app";
const DEMO_PASSWORD = "demo123";
// Pre-hashed so bcrypt compare works without storing plaintext
const DEMO_HASH = await bcrypt.hash(DEMO_PASSWORD, 10); // run once, hardcode result
// Hardcode the result to avoid async top-level: "$2a$10$..."
const DEMO_HASH_STATIC = "$2a$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi"; // = "password" for bcrypt

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;
        const email = credentials.email as string;
        const password = credentials.password as string;

        // 1. Try real DB first
        try {
          const { getUserByEmail } = await import("@/lib/db");
          const user = await getUserByEmail(email);
          if (user) {
            const valid = await bcrypt.compare(password, user.passwordHash);
            if (!valid) return null;
            return { id: user.id, email: user.email, name: user.name };
          }
        } catch {
          // DB unavailable (preview deploy with no real DATABASE_URL) — fall through to demo
        }

        // 2. Demo credentials fallback
        if (
          email === DEMO_EMAIL &&
          password === DEMO_PASSWORD
        ) {
          return { id: "demo-user-id", email: DEMO_EMAIL, name: "Demo User" };
        }

        return null;
      },
    }),
  ],
  callbacks: {
    session({ session, token }) {
      if (token.sub) (session.user as { id?: string }).id = token.sub;
      return session;
    },
  },
  session: { strategy: "jwt" },
  pages: { signIn: "/sign-in" },
  secret: process.env.NEXTAUTH_SECRET ?? "preview-dev-secret",
  trustHost: true,
});
```

## "Try Demo" button component
```typescript
"use client";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function TryDemoButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleDemo() {
    setLoading(true);
    const result = await signIn("credentials", {
      email: "demo@demo.app",
      password: "demo123",
      redirect: false,
    });
    if (result?.ok) {
      router.push("/dashboard");
    } else {
      setLoading(false);
      alert("Demo login failed — check NEXTAUTH_SECRET is set");
    }
  }

  return (
    <button onClick={handleDemo} disabled={loading}>
      {loading ? "Signing in..." : "Try Demo (no signup)"}
    </button>
  );
}
```

## Usage on sign-in page
```typescript
import { TryDemoButton } from "@/components/TryDemoButton";

export default function SignInPage() {
  return (
    <div>
      <SignInForm />
      <hr />
      <TryDemoButton />
    </div>
  );
}
```

## Required env vars
```
NEXTAUTH_SECRET=any-string-works-for-preview   # required even on preview
DATABASE_URL=placeholder                        # can be fake on preview — fallback handles it
```

## Notes
- The demo fallback only activates when the real DB lookup throws or returns nothing
- In production with a real DB, the demo credentials still work unless you remove the fallback block
- To disable demo in prod: `if (process.env.NODE_ENV === "production") return null;` before the fallback block
