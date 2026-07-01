---
title: Env Var Validation at Build Time (t3-env / Zod)
tags: [env, deployment, validation, zod, typescript]
category: deployment
applies_to: [technical, technical_scaffold]
---

# Env Var Validation at Build Time (t3-env / Zod)

Fails the build immediately if a required env var is missing or wrong type — no more silent `undefined` in production.

## Install
```bash
npm install @t3-oss/env-nextjs zod
```

## `env.ts` (project root)
```typescript
import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  /**
   * Server-side env vars — never sent to the browser.
   * Available in Server Components, Route Handlers, Server Actions.
   */
  server: {
    DATABASE_URL: z.string().url(),
    NEXTAUTH_SECRET: z.string().min(32),
    STRIPE_SECRET_KEY: z.string().startsWith("sk_"),
    STRIPE_WEBHOOK_SECRET: z.string().startsWith("whsec_"),
    RESEND_API_KEY: z.string().startsWith("re_"),
    // Optional with default
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  },

  /**
   * Client-side env vars — must be prefixed NEXT_PUBLIC_.
   * Bundled into the browser build.
   */
  client: {
    NEXT_PUBLIC_SUPABASE_URL: z.string().url(),
    NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().min(1),
    NEXT_PUBLIC_APP_URL: z.string().url().default("http://localhost:3000"),
  },

  /**
   * Destructure all client vars here so t3-env can validate them at runtime.
   * Must match the keys above exactly.
   */
  experimental__runtimeEnv: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
  },

  /**
   * Skip validation during CI lint/type-check steps that don't need real values.
   */
  skipValidation: !!process.env.SKIP_ENV_VALIDATION,
});
```

## `next.config.ts`
```typescript
import "./env"; // triggers validation at build time — import must be top-level

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // your other config
};

export default nextConfig;
```

## Usage anywhere in the app
```typescript
import { env } from "@/env";

// Server Component / Route Handler / Server Action
const stripe = new Stripe(env.STRIPE_SECRET_KEY);

// Client Component (only NEXT_PUBLIC_ vars available here)
const supabaseUrl = env.NEXT_PUBLIC_SUPABASE_URL;
```

## Notes
- TypeScript infers the exact type of each var (e.g. `string`, `"development" | "test" | "production"`)
- Build output shows which var is missing: `❌ Invalid environment variables: STRIPE_SECRET_KEY: Required`
- Set `SKIP_ENV_VALIDATION=1` in CI jobs that only run `tsc` or `eslint` without a real `.env`
- Never access `process.env.XYZ` directly — always import from `env.ts` to get type safety
