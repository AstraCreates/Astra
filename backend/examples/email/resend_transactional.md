---
title: Resend — Transactional Email (Welcome, Reset, Notifications)
tags: [email, resend, transactional, next.js, react-email]
category: email
applies_to: [technical, technical_scaffold, marketing_outreach, ops]
---

# Resend Transactional Email

## Packages
```bash
npm install resend @react-email/components
```

## `lib/email.ts`
```typescript
import { Resend } from "resend";

export const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendWelcomeEmail(to: string, name: string) {
  await resend.emails.send({
    from: "Astra <hello@yourdomain.com>",
    to,
    subject: "Welcome to Astra",
    html: `<p>Hi ${name}, welcome aboard!</p>`,
  });
}

export async function sendPasswordResetEmail(to: string, resetUrl: string) {
  await resend.emails.send({
    from: "Astra <hello@yourdomain.com>",
    to,
    subject: "Reset your password",
    html: `<p><a href="${resetUrl}">Click here</a> to reset your password. Link expires in 1 hour.</p>`,
  });
}
```

## Trigger on sign-up (API route)
```typescript
import { sendWelcomeEmail } from "@/lib/email";

// Inside your register route:
await sendWelcomeEmail(email, name ?? email);
```

## React Email template (optional, cleaner HTML)
```typescript
import { Html, Text, Button, Container } from "@react-email/components";

export function WelcomeEmail({ name, dashboardUrl }: { name: string; dashboardUrl: string }) {
  return (
    <Html>
      <Container>
        <Text>Hi {name},</Text>
        <Text>Your account is ready.</Text>
        <Button href={dashboardUrl}>Go to dashboard</Button>
      </Container>
    </Html>
  );
}
```

## Required env vars
```
RESEND_API_KEY=re_...   # from resend.com dashboard
```

## Notes
- Free tier: 100 emails/day, 3000/month — sufficient for MVP
- Must verify your sending domain in Resend dashboard (DNS TXT record)
- Use `onboarding@resend.dev` as `from` for testing (no domain verification needed)
- Resend supports webhooks for delivery/open/bounce tracking
