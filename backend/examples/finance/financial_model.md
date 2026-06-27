---
title: Startup Financial Model (3-statement-lite, SaaS)
category: research
tags: finance model projections revenue saas mrr arr cac ltv burn runway
applies_to: finance_model finance_fundraise research_financial research
---

Driver-based monthly model skeleton. Build assumptions FIRST, then formulas. Replace `{{...}}`.
Keep every output traceable to a driver — investors probe assumptions, not totals.

## Drivers (the only numbers you hand-enter)
- New customers/mo: {{n}} (or leads × conversion %)
- Avg revenue/customer/mo (ARPA): {{$}}
- Monthly churn %: {{%}}
- Gross margin %: {{%}}
- CAC: {{$}}  | Opex/mo (team, tools, rent): {{$}}
- Starting cash: {{$}}

## Revenue build (monthly)
- Customers(t) = Customers(t-1) × (1 − churn) + New(t)
- MRR(t) = Customers(t) × ARPA
- ARR = MRR × 12

## Unit economics
- LTV = (ARPA × gross_margin%) / churn%
- LTV:CAC ratio = LTV / CAC   (target ≥ 3)
- CAC payback (months) = CAC / (ARPA × gross_margin%)

## Cash / runway
- Gross profit(t) = MRR(t) × gross_margin%
- Burn(t) = Opex(t) + (New(t) × CAC) − Gross profit(t)
- Cash(t) = Cash(t-1) − Burn(t)
- Runway = Cash / avg monthly burn

## Outputs to present
- MRR/ARR curve (12–36 mo), customers, burn, runway (months to $0), LTV:CAC, CAC payback.
- 3 scenarios: conservative / base / optimistic (vary New/mo + churn).

Rules:
- Show assumptions on their own tab/section; never bury a hand-entered number in a formula.
- If a driver is a guess, label it and give the source/comparable you anchored to.
