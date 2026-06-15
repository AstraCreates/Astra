---
title: Tailwind Landing Page — Hero + Features + CTA
tags: [tailwind, landing, hero, cta, features, next.js, marketing]
category: design
applies_to: [web, technical, design, marketing_seo]
---

# Tailwind Landing Page

Full landing page: hero, feature grid, CTA section. Drop-in for any Next.js project.

## `app/page.tsx`
```typescript
import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-white text-gray-900 font-sans">
      <Nav />
      <Hero />
      <Features />
      <CTA />
      <Footer />
    </main>
  );
}

function Nav() {
  return (
    <nav className="flex items-center justify-between px-6 py-4 border-b border-gray-100 max-w-6xl mx-auto">
      <span className="text-lg font-bold tracking-tight">YourBrand</span>
      <div className="flex items-center gap-6 text-sm text-gray-600">
        <Link href="#features" className="hover:text-gray-900 transition-colors">Features</Link>
        <Link href="#pricing" className="hover:text-gray-900 transition-colors">Pricing</Link>
        <Link
          href="/sign-up"
          className="bg-black text-white px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors font-medium"
        >
          Get started
        </Link>
      </div>
    </nav>
  );
}

function Hero() {
  return (
    <section className="max-w-4xl mx-auto text-center px-6 pt-24 pb-20">
      <div className="inline-flex items-center gap-2 bg-blue-50 text-blue-700 text-xs font-medium px-3 py-1 rounded-full mb-6">
        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full" />
        Now in public beta
      </div>
      <h1 className="text-5xl font-bold tracking-tight leading-tight mb-6">
        The fastest way to<br />
        <span className="text-blue-600">launch your idea</span>
      </h1>
      <p className="text-xl text-gray-500 max-w-2xl mx-auto mb-10">
        Ship your product in days, not months. Everything you need to go from
        idea to paying customers — built in.
      </p>
      <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
        <Link
          href="/sign-up"
          className="bg-black text-white px-6 py-3 rounded-lg font-medium hover:bg-gray-800 transition-colors w-full sm:w-auto text-center"
        >
          Start for free
        </Link>
        <Link
          href="#demo"
          className="text-gray-600 hover:text-gray-900 px-6 py-3 rounded-lg font-medium border border-gray-200 hover:border-gray-300 transition-colors w-full sm:w-auto text-center"
        >
          Watch demo →
        </Link>
      </div>
      <p className="mt-4 text-sm text-gray-400">No credit card required · Cancel anytime</p>
    </section>
  );
}

const FEATURES = [
  {
    icon: "⚡",
    title: "Blazing fast",
    desc: "Built on Next.js 15 and Vercel Edge — your users get sub-100ms responses globally.",
  },
  {
    icon: "🔐",
    title: "Auth included",
    desc: "Google OAuth and email/password auth out of the box. No third-party auth fees.",
  },
  {
    icon: "💳",
    title: "Payments ready",
    desc: "Stripe Checkout and subscription billing pre-wired. Go from free to paid in minutes.",
  },
  {
    icon: "📊",
    title: "Analytics built-in",
    desc: "Track signups, conversions, and retention without adding another SDK.",
  },
  {
    icon: "🎨",
    title: "Design system",
    desc: "Tailwind + shadcn/ui components. Looks great out of the box, fully customizable.",
  },
  {
    icon: "🚀",
    title: "One-command deploy",
    desc: "Push to GitHub → Vercel deploys automatically. SSL, CDN, and preview URLs included.",
  },
];

function Features() {
  return (
    <section id="features" className="max-w-6xl mx-auto px-6 py-20">
      <div className="text-center mb-14">
        <h2 className="text-3xl font-bold tracking-tight mb-4">Everything you need, nothing you don't</h2>
        <p className="text-lg text-gray-500 max-w-xl mx-auto">
          We obsessed over the boilerplate so you can focus on what makes your product unique.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {FEATURES.map((f) => (
          <div key={f.title} className="p-6 rounded-xl border border-gray-100 hover:border-gray-200 transition-colors">
            <div className="text-2xl mb-3">{f.icon}</div>
            <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
            <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function CTA() {
  return (
    <section className="bg-black text-white mx-6 rounded-2xl max-w-6xl lg:mx-auto px-8 py-16 text-center mb-20">
      <h2 className="text-3xl font-bold mb-4">Ready to ship?</h2>
      <p className="text-gray-400 text-lg mb-8 max-w-lg mx-auto">
        Join 1,200+ founders who launched their products with us this year.
      </p>
      <Link
        href="/sign-up"
        className="inline-block bg-white text-black px-8 py-3 rounded-lg font-semibold hover:bg-gray-100 transition-colors"
      >
        Get started free →
      </Link>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-gray-100 px-6 py-8 max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-400">
      <span>© 2024 YourBrand, Inc.</span>
      <div className="flex gap-6">
        <Link href="/privacy" className="hover:text-gray-600 transition-colors">Privacy</Link>
        <Link href="/terms" className="hover:text-gray-600 transition-colors">Terms</Link>
        <Link href="mailto:hello@yourbrand.com" className="hover:text-gray-600 transition-colors">Contact</Link>
      </div>
    </footer>
  );
}
```

## Required globals (`app/globals.css`)
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

## `tailwind.config.ts`
```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
export default config;
```

## Notes
- Replace `YourBrand` everywhere with the actual product name
- FEATURES array drives the grid — edit copy, no layout changes needed
- Hero badge (`Now in public beta`) → remove or change once launched
- Dark CTA section stands out; keep it black even if brand uses color
