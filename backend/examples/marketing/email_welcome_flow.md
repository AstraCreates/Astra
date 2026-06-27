---
title: Welcome / Onboarding Email Flow (5-email drip)
category: email
tags: email welcome onboarding drip nurture lifecycle klaviyo resend activation
applies_to: marketing marketing_content marketing_outreach ops
---

Proven 5-email welcome sequence for a new signup/subscriber. Fill the `{{placeholders}}`.
Send times are relative to signup. Keep each email one idea + one CTA.

## Email 1 — Welcome + deliver the promise (send: immediately)
Subject: Welcome to {{product}} — here's your {{lead_magnet}}
Preview: Plus the fastest way to get your first win.
Body:
- One line that restates the outcome they came for.
- Deliver the asset / first step link immediately.
- Set expectation: "Over the next few days I'll show you how to {{core_outcome}}."
CTA: {{primary_action}} (e.g. "Open your dashboard")

## Email 2 — Quick win (send: +1 day)
Subject: The 5-minute {{product}} win most people miss
Body:
- One concrete, tiny action that produces visible value fast.
- Show the before→after.
CTA: "Try it now"

## Email 3 — Overcome the #1 objection (send: +3 days)
Subject: "But will {{product}} actually work for {{ICP}}?"
Body:
- Name the top objection honestly.
- Answer with a proof point: metric, mini case study, or screenshot.
CTA: "See how {{customer}} did it"

## Email 4 — Social proof + use cases (send: +5 days)
Subject: How {{ICP}} use {{product}}
Body:
- 3 short use cases mapped to different segments.
- 1 testimonial with a number.
CTA: "Find your use case"

## Email 5 — Offer / upgrade (send: +7 days)
Subject: Ready to {{bigger_outcome}}?
Body:
- Recap the value delivered so far.
- Make the offer (trial→paid, demo, discount with deadline).
CTA: "{{offer_action}}"

Notes:
- Personalize subject with first name only if data is reliable.
- Each email: 1 CTA, <150 words, mobile-first, plain text outperforms heavy HTML for activation.
- Klaviyo: build as a Flow triggered on list-join. Resend: schedule via cron/queue.
