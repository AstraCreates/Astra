---
title: Stripe Checkout + Webhook — Next.js
tags: [payments, stripe, checkout, webhook, next.js]
category: payments
applies_to: [technical, technical_scaffold, ops]
---

# Stripe Checkout Session + Webhook

## Packages
```bash
npm install stripe @stripe/stripe-js
```

## Create checkout session `app/api/checkout/route.ts`
```typescript
import Stripe from "stripe";
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth"; // or supabase equivalent

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { priceId } = await req.json();

  const checkoutSession = await stripe.checkout.sessions.create({
    mode: "subscription",  // or "payment" for one-time
    customer_email: session.user.email!,
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${process.env.NEXT_PUBLIC_BASE_URL}/dashboard?upgraded=1`,
    cancel_url: `${process.env.NEXT_PUBLIC_BASE_URL}/pricing`,
    metadata: { userId: (session.user as { id?: string }).id ?? "" },
  });

  return NextResponse.json({ url: checkoutSession.url });
}
```

## Checkout button (client component)
```typescript
"use client";
export function CheckoutButton({ priceId }: { priceId: string }) {
  async function handleClick() {
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priceId }),
    });
    const { url } = await res.json();
    window.location.href = url;
  }
  return <button onClick={handleClick}>Upgrade</button>;
}
```

## Webhook `app/api/webhooks/stripe/route.ts`
```typescript
import Stripe from "stripe";
import { NextRequest, NextResponse } from "next/server";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function POST(req: NextRequest) {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature")!;

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch {
    return NextResponse.json({ error: "Bad signature" }, { status: 400 });
  }

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      const userId = session.metadata?.userId;
      // TODO: update DB — mark user as subscribed
      break;
    }
    case "customer.subscription.deleted": {
      // TODO: revoke access
      break;
    }
  }

  return NextResponse.json({ received: true });
}

// Stripe requires raw body for signature verification
export const config = { api: { bodyParser: false } };
```

## Required env vars
```
STRIPE_SECRET_KEY=sk_live_...   # or sk_test_... for dev
STRIPE_WEBHOOK_SECRET=whsec_... # from Stripe dashboard → Webhooks
NEXT_PUBLIC_BASE_URL=https://yourapp.com
```

## Local webhook testing
```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
```

## Notes
- Use `sk_test_` keys during development; switch to `sk_live_` for production
- Always verify webhook signature — never trust raw event data
- For one-time payments: `mode: "payment"` instead of `"subscription"`
