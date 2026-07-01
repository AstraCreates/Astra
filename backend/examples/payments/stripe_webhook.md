---
title: Stripe Webhook Handler (Next.js App Router)
tags: [stripe, webhook, payments, next.js, app-router]
category: payments
applies_to: [technical, technical_scaffold]
---

# Stripe Webhook Handler (Next.js App Router)

Handles `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`.
Raw body must be read with `request.text()` — do not use `request.json()` or Stripe signature verification breaks.

## `app/api/webhooks/stripe/route.ts`
```typescript
import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, { apiVersion: "2024-06-20" });

export async function POST(request: NextRequest) {
  const body = await request.text();
  const sig = request.headers.get("stripe-signature");

  if (!sig) return NextResponse.json({ error: "No signature" }, { status: 400 });

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch (err) {
    console.error("Webhook signature verification failed:", err);
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId = session.metadata?.userId;
        const customerId = session.customer as string;
        const subscriptionId = session.subscription as string;
        // Mark user as active subscriber in your DB
        await activateSubscription({ userId, customerId, subscriptionId });
        break;
      }

      case "customer.subscription.updated": {
        const sub = event.data.object as Stripe.Subscription;
        const status = sub.status; // "active" | "past_due" | "canceled" | etc.
        await updateSubscriptionStatus({ subscriptionId: sub.id, status });
        break;
      }

      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        await cancelSubscription({ subscriptionId: sub.id });
        break;
      }

      default:
        console.log(`Unhandled event type: ${event.type}`);
    }
  } catch (err) {
    console.error("Webhook handler error:", err);
    return NextResponse.json({ error: "Handler failed" }, { status: 500 });
  }

  return NextResponse.json({ received: true }, { status: 200 });
}

// Stub DB helpers — replace with your actual DB calls
async function activateSubscription(opts: { userId?: string; customerId: string; subscriptionId: string }) {
  // e.g. await db.user.update({ where: { id: opts.userId }, data: { plan: "pro", stripeCustomerId: opts.customerId } });
  console.log("Activate subscription:", opts);
}
async function updateSubscriptionStatus(opts: { subscriptionId: string; status: string }) {
  console.log("Update subscription status:", opts);
}
async function cancelSubscription(opts: { subscriptionId: string }) {
  console.log("Cancel subscription:", opts);
}
```

## Required env vars
```
STRIPE_SECRET_KEY=sk_live_...        # or sk_test_... for local dev
STRIPE_WEBHOOK_SECRET=whsec_...      # from Stripe Dashboard > Webhooks
```

## Local testing
```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
# prints a whsec_ to paste into .env.local
```

## Notes
- `export const config = { api: { bodyParser: false } }` is NOT needed in App Router — `request.text()` handles raw body directly
- Always return 200 quickly; offload slow DB work to a background queue if needed
- Pass `userId` in `metadata` when creating the Checkout Session so you can link it back
