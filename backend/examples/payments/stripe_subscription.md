---
title: Stripe Subscription Billing — Checkout + Portal + Webhooks
tags: [stripe, subscription, billing, checkout, webhook, next.js, payments]
category: payments
applies_to: [technical, technical_scaffold, ops]
---

# Stripe Subscription Billing

Full recurring billing: checkout, customer portal, webhook sync.

## `lib/stripe.ts`
```typescript
import Stripe from "stripe";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2024-06-20",
});

export const PLANS = {
  starter: {
    priceId: process.env.STRIPE_STARTER_PRICE_ID!,
    name: "Starter",
    amount: 2900,   // $29/mo in cents
  },
  pro: {
    priceId: process.env.STRIPE_PRO_PRICE_ID!,
    name: "Pro",
    amount: 7900,   // $79/mo in cents
  },
} as const;

export type PlanKey = keyof typeof PLANS;
```

## `app/api/billing/checkout/route.ts`
```typescript
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { stripe, PLANS, PlanKey } from "@/lib/stripe";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { plan } = await req.json() as { plan: PlanKey };
  if (!PLANS[plan]) {
    return NextResponse.json({ error: "Invalid plan" }, { status: 400 });
  }

  const checkout = await stripe.checkout.sessions.create({
    mode: "subscription",
    payment_method_types: ["card"],
    line_items: [{ price: PLANS[plan].priceId, quantity: 1 }],
    customer_email: session.user.email,
    success_url: `${process.env.NEXT_PUBLIC_BASE_URL}/dashboard?upgraded=1`,
    cancel_url: `${process.env.NEXT_PUBLIC_BASE_URL}/pricing`,
    metadata: { userId: (session.user as { id?: string }).id ?? "" },
  });

  return NextResponse.json({ url: checkout.url });
}
```

## `app/api/billing/portal/route.ts`
```typescript
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { stripe } from "@/lib/stripe";
import { getCustomerByEmail } from "@/lib/db";

export async function POST() {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const customer = await getCustomerByEmail(session.user.email);
  if (!customer?.stripe_customer_id) {
    return NextResponse.json({ error: "No billing account" }, { status: 404 });
  }

  const portal = await stripe.billingPortal.sessions.create({
    customer: customer.stripe_customer_id,
    return_url: `${process.env.NEXT_PUBLIC_BASE_URL}/dashboard/billing`,
  });

  return NextResponse.json({ url: portal.url });
}
```

## `app/api/webhooks/stripe/route.ts`
```typescript
import { NextRequest, NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";
import { updateSubscription } from "@/lib/db";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature")!;

  let event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch {
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object;
      await updateSubscription({
        userId: session.metadata?.userId ?? "",
        stripeCustomerId: session.customer as string,
        status: "active",
        plan: "starter",  // resolve from price ID if multiple plans
      });
      break;
    }
    case "customer.subscription.updated":
    case "customer.subscription.deleted": {
      const sub = event.data.object;
      await updateSubscription({
        stripeCustomerId: sub.customer as string,
        status: sub.status === "active" ? "active" : "inactive",
      });
      break;
    }
  }

  return NextResponse.json({ received: true });
}
```

## Pricing UI component
```typescript
"use client";
import { useState } from "react";
import { PLANS, PlanKey } from "@/lib/stripe";

export function PricingCards() {
  const [loading, setLoading] = useState<PlanKey | null>(null);

  async function subscribe(plan: PlanKey) {
    setLoading(plan);
    const res = await fetch("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    const { url } = await res.json();
    window.location.href = url;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 max-w-2xl mx-auto">
      {(Object.entries(PLANS) as [PlanKey, typeof PLANS[PlanKey]][]).map(([key, plan]) => (
        <div key={key} className="border rounded-xl p-6">
          <h3 className="font-semibold text-lg mb-1">{plan.name}</h3>
          <p className="text-3xl font-bold mb-6">
            ${plan.amount / 100}<span className="text-sm font-normal text-gray-500">/mo</span>
          </p>
          <button
            onClick={() => subscribe(key)}
            disabled={loading === key}
            className="w-full bg-black text-white py-2.5 rounded-lg font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors"
          >
            {loading === key ? "Redirecting..." : `Start ${plan.name}`}
          </button>
        </div>
      ))}
    </div>
  );
}
```

## Required env vars
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...    # from Stripe Dashboard → Webhooks
STRIPE_STARTER_PRICE_ID=price_...  # create in Stripe Dashboard → Products
STRIPE_PRO_PRICE_ID=price_...
NEXT_PUBLIC_BASE_URL=https://your-app.vercel.app
```

## Stripe Dashboard setup
1. Products → Add product → Add recurring price (monthly) → copy Price ID → env var
2. Webhooks → Add endpoint → `https://your-app.vercel.app/api/webhooks/stripe`
3. Events to listen: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
4. Copy webhook signing secret → `STRIPE_WEBHOOK_SECRET`

## Gotchas
- `STRIPE_WEBHOOK_SECRET` is per-endpoint — regenerate if you delete and recreate the webhook
- `customer_email` pre-fills checkout but Stripe creates a new customer if not already one
- For production, store `stripe_customer_id` from webhook, not from checkout (race condition)
- Test webhooks locally: `stripe listen --forward-to localhost:3000/api/webhooks/stripe`
