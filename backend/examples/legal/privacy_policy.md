---
title: Privacy Policy Template — GDPR + CCPA Compliant SaaS
tags: [legal, privacy, gdpr, ccpa, policy, template]
category: legal
applies_to: [legal, legal_docs, technical_scaffold]
---

# Privacy Policy Template

Use this as a starting scaffold. Replace all `{placeholders}`.

---

## Privacy Policy

**Last updated:** {date}

### 1. Who we are
{Company Name} ("we", "us", "our") operates {product_name} at {website_url}. Contact: {privacy_email}.

### 2. What data we collect
- **Account data**: email, name, password hash (never plaintext)
- **Usage data**: pages visited, features used, timestamps — for product improvement
- **Payment data**: billing address, last 4 digits of card — full card data processed by Stripe, never stored by us
- **Communications**: emails you send us, support tickets

### 3. How we use your data
- Provide and improve the service
- Send transactional emails (signup confirmation, password reset, receipts)
- Send product updates (you can unsubscribe at any time)
- Comply with legal obligations

We do NOT sell your data. We do NOT use your data for advertising.

### 4. Data sharing
We share data only with:
- **Stripe** — payment processing (PCI DSS compliant)
- **Supabase / {database_provider}** — data storage (SOC 2 compliant)
- **Resend / {email_provider}** — transactional email
- **Vercel** — hosting (SOC 2 compliant)
- Law enforcement when legally required

### 5. Data retention
- Account data: retained while your account is active + 30 days after deletion
- Payment records: 7 years (tax/legal requirement)
- Logs: 90 days

### 6. Your rights (GDPR / CCPA)
You have the right to:
- Access your data — email {privacy_email}
- Correct inaccurate data — update in account settings
- Delete your data — email {privacy_email} or use in-app deletion
- Export your data — email {privacy_email}
- Opt out of marketing emails — unsubscribe link in every email

We respond to requests within 30 days.

### 7. Cookies
We use:
- **Essential cookies**: session authentication (required, cannot opt out)
- **Analytics cookies**: {analytics_provider} — aggregate usage stats (opt out available)

### 8. Children's privacy
Our service is not directed to children under 13. We do not knowingly collect data from children.

### 9. Security
We use industry-standard security: HTTPS, encrypted passwords (bcrypt), role-based access control, and SOC 2 compliant infrastructure.

### 10. Changes to this policy
We'll email users 30 days before material changes. Continued use after changes = acceptance.

### 11. Contact
{Company Name} | {address} | {privacy_email}

---

## Notes for legal agents
- This template covers GDPR (EU) and CCPA (California) basics
- For HIPAA compliance (health data): requires BAAs with all vendors — consult a lawyer
- For financial data: additional requirements apply — consult a lawyer
- `{privacy_email}` should be a monitored inbox, not a noreply address
- Post this at `/privacy` and link from footer + sign-up flow
