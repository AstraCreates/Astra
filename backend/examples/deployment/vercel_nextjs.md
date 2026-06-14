---
title: Vercel Deployment — Next.js 15 Config & Best Practices
tags: [deployment, vercel, next.js, env, build]
category: deployment
applies_to: [technical, technical_scaffold, technical_infra]
---

# Vercel Next.js 15 Deployment

## `next.config.mjs`
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow images from external domains
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.supabase.co" },
      { protocol: "https", hostname: "lh3.googleusercontent.com" }, // Google avatars
    ],
  },
  // Suppress known harmless warnings
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
```

## Required env vars on Vercel
Set in Vercel Dashboard → Project → Settings → Environment Variables:
```
NEXTAUTH_SECRET=<openssl rand -hex 32>
NEXTAUTH_URL=https://your-app.vercel.app
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_BASE_URL=https://your-app.vercel.app
```

## Add domain to Google OAuth callback URIs
When deploying to Vercel, add to Google Cloud Console:
- Authorized redirect URI: `https://your-app.vercel.app/api/auth/callback/google`

## Dynamic routes that use auth
```typescript
// CORRECT — don't force static generation on auth pages
export const dynamic = "force-dynamic";

// WRONG — this will break auth
// export const dynamic = "error";
```

## API routes with large response bodies
```typescript
export const maxDuration = 60; // seconds, Vercel Pro allows up to 300
```

## Notes
- Vercel auto-detects Next.js — no build command customization needed
- `NEXTAUTH_URL` must match the actual deployment URL exactly
- Preview deployments get unique URLs — set `NEXTAUTH_URL` to the main domain, not preview
- Free tier: 100GB bandwidth, 6000 build minutes/month
