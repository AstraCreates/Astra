---
title: Resend Transactional Email (React Email template)
tags: [email, resend, transactional, react-email]
category: email
applies_to: [technical, technical_scaffold]
---

# Resend Transactional Email (React Email template)

Resend client wrapper + a typed React Email component + a Route Handler + a Server Action example.

## Install
```bash
npm install resend @react-email/components
```

## `lib/email.ts` — Resend client wrapper
```typescript
import { Resend } from "resend";
import { WelcomeEmail } from "@/emails/WelcomeEmail";

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendWelcomeEmail(to: string, name: string) {
  const { data, error } = await resend.emails.send({
    from: "Acme <onboarding@yourdomain.com>", // must be a verified domain in Resend
    to,
    subject: "Welcome to Acme!",
    react: WelcomeEmail({ name }),
  });

  if (error) {
    console.error("Failed to send welcome email:", error);
    throw new Error(error.message);
  }

  return data;
}

// Generic helper for other email types
export async function sendEmail(opts: {
  to: string;
  subject: string;
  react: React.ReactElement;
}) {
  return resend.emails.send({
    from: "Acme <noreply@yourdomain.com>",
    ...opts,
  });
}
```

## `emails/WelcomeEmail.tsx` — React Email component
```typescript
import {
  Body, Button, Container, Head, Heading, Hr,
  Html, Preview, Section, Text,
} from "@react-email/components";

interface WelcomeEmailProps {
  name: string;
}

export function WelcomeEmail({ name }: WelcomeEmailProps) {
  return (
    <Html>
      <Head />
      <Preview>Welcome to Acme, {name}!</Preview>
      <Body style={{ backgroundColor: "#f6f9fc", fontFamily: "sans-serif" }}>
        <Container style={{ maxWidth: "580px", margin: "0 auto", padding: "20px" }}>
          <Heading>Welcome, {name}!</Heading>
          <Text>Thanks for signing up. Click below to get started:</Text>
          <Section>
            <Button
              href="https://yourdomain.com/dashboard"
              style={{ backgroundColor: "#0070f3", color: "#fff", padding: "12px 24px", borderRadius: "6px" }}
            >
              Go to Dashboard
            </Button>
          </Section>
          <Hr />
          <Text style={{ color: "#888", fontSize: "12px" }}>
            You received this email because you signed up at yourdomain.com.
          </Text>
        </Container>
      </Body>
    </Html>
  );
}

export default WelcomeEmail;
```

## `app/api/send-email/route.ts` — Route Handler
```typescript
import { NextRequest, NextResponse } from "next/server";
import { sendWelcomeEmail } from "@/lib/email";

export async function POST(request: NextRequest) {
  const { email, name } = await request.json();
  if (!email || !name) {
    return NextResponse.json({ error: "Missing email or name" }, { status: 400 });
  }
  try {
    const data = await sendWelcomeEmail(email, name);
    return NextResponse.json({ id: data?.id }, { status: 200 });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
```

## Sending from a Server Action
```typescript
"use server";
import { sendWelcomeEmail } from "@/lib/email";

export async function onboardUser(formData: FormData) {
  const email = formData.get("email") as string;
  const name = formData.get("name") as string;
  // ... create user in DB ...
  await sendWelcomeEmail(email, name);
}
```

## Required env vars
```
RESEND_API_KEY=re_...    # from resend.com/api-keys
```

## Notes
- Sender domain must be verified in Resend; use `onboarding@resend.dev` as `from` for testing without a domain
- Preview emails locally: `npx react-email dev` — opens a browser preview of all `emails/` components
- Rate limit on free plan: 100 emails/day, 3,000/month
- Resend supports webhooks for delivery/open/bounce tracking (`email.delivered`, `email.bounced`)
