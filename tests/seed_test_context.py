"""
Write pre-built context notes to the obsidian vault for test_founder.
Run once on the server. Every subsequent agent test will call obsidian_read
and find this brief, skipping redundant research/planning.

Usage:
  python3 tests/seed_test_context.py
"""
from pathlib import Path
import os

VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "~/agent-workspace")).expanduser()
FOUNDER_ID = "test_founder"
SESSION_ID = "seed_context_v1"

SESSION_DIR = VAULT / "founders" / FOUNDER_ID / "sessions" / SESSION_ID
SESSION_DIR.mkdir(parents=True, exist_ok=True)

COMPANY = "InvoiceAI"
GOAL = "Build a SaaS for freelancers to track invoices and get paid faster with AI-powered payment reminders."

# ─── Shared market brief injected into every agent ───────────────────────────
MARKET_BRIEF = f"""
# {COMPANY} — Company Brief

## Goal
{GOAL}

## Company
- Name: {COMPANY}
- Category: B2B SaaS, freelancer tools
- Stage: Pre-launch / seed
- Target customer: Freelancers earning $50k–$200k/year (designers, developers, consultants, writers)

## Market
- TAM: $14B (global invoicing + payments software)
- SAM: $3.2B (freelancer-specific tools, US/UK/AU/CA)
- SOM: $32M (AI-native, 1% of SAM in 3 years)
- CAGR: 11.4% through 2028
- Competitors: FreshBooks ($500M ARR), Wave (free, acquired by H&R Block), HoneyBook ($2B valuation), Bonsai, Invoice Ninja
- Differentiation: AI drafts invoices from calendar/email context, auto-sends reminders at optimal times, predicts payment likelihood per client

## Pricing
- Free tier: 3 active clients
- Pro: $19/month — unlimited clients, AI reminders, payment analytics
- Business: $49/month — team seats, white-label, Stripe/PayPal integration
- Target LTV: $684 (Pro, 36-month retention)
- CAC target: <$85 via SEO + product-led growth

## ICP
- Job: Freelance designer or developer
- Revenue: $80k–$150k/year
- Pain: Chasing late payments, manual invoice creation, no visibility into payment status
- Tools: Already uses Notion, Figma, GitHub, Stripe or PayPal
- Willingness to pay: $15–$25/month

## Technical Stack
- Frontend: Next.js 14, Tailwind CSS
- Backend: FastAPI (Python 3.13), PostgreSQL (Supabase), Redis
- Auth: Clerk
- Payments: Stripe
- AI: OpenAI GPT-4o for invoice extraction, reminder copy generation
- Hosting: Vercel (frontend), Railway or Fly.io (backend)
- Repo: github.com/invoiceai/app

## Legal
- Entity: Delaware C-Corp (incorporated)
- IP: All code owned by company, founder IP assignment signed
- Privacy: GDPR + CCPA compliant (data processing agreement in place)
- Terms: SaaS subscription terms, no refunds after 7-day trial
- Key risk: PCI-DSS compliance for payment data (mitigated by delegating to Stripe)

## Marketing
- Primary channel: SEO (target: "freelancer invoice tracker", "best invoicing app freelancers")
- Secondary: Product Hunt launch, freelancer Reddit/Discord communities
- Content: weekly "get paid faster" tips, Instagram Reels
- Email list: 1,200 waitlist signups pre-launch
- Launch date: 30 days from now

## Fundraising
- Raise: $750k SAFE, $6M cap, 20% discount
- Use: 18 months runway, 2 engineers + 1 marketer
- Target investors: Pre-seed funds focused on future-of-work (Hustle Fund, Precursor, Backstage)
- Traction to show: 1,200 waitlist, 3 paying beta users at $49/month
"""

# ─── Agent-specific notes ────────────────────────────────────────────────────
NOTES: dict[str, str] = {}

# Research agents — already have the brief, skip additional searches
for agent in ["research", "research_competitors", "research_execution",
              "research_market", "research_financial", "research_regulatory"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Prior Research Completed
- Market sizing validated via Statista, Grand View Research, G2 reviews
- Competitor pricing scraped: FreshBooks $19–$55/mo, Wave free, HoneyBook $16–$66/mo
- Customer interviews: 12 freelancers, avg late payment wait = 18 days, 3 follow-up emails
- Patent landscape: no blocking patents on AI invoice reminders (USPTO search done)
- Regulatory: no specific invoicing regulation; GDPR applies to EU customers (cookie consent + DPA)
- Financial benchmarks: SaaS invoicing tools avg gross margin 78%, CAC payback <12 months at Pro tier

## Status
Context loaded. Proceed directly to specialized analysis — do not re-run basic market research.
"""

# Legal agents
for agent in ["legal", "legal_docs", "legal_entity", "legal_ip"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Legal Context
- Entity: Delaware C-Corp formed (EIN: pending)
- IP assignment: template drafted, founders to sign at incorporation
- Privacy policy: GDPR + CCPA template needed, no personal health data processed
- Terms of service: SaaS subscription, auto-renewal, 7-day cancellation window
- NDA: standard mutual NDA needed for investor conversations
- Patent: No blocking patents found on AI invoice reminder workflows
- Trademark: "{COMPANY}" not registered — filing recommended in Class 36 (financial services)

## Status
Context loaded. Draft requested documents immediately.
"""

# Web agent
NOTES["web"] = MARKET_BRIEF + f"""
## Landing Page Brief
- Headline: "Get paid faster. Stop chasing invoices."
- Subheadline: "AI-powered invoicing for freelancers. Auto-reminders, payment predictions, zero manual follow-up."
- Hero CTA: "Start free — no credit card" → /signup
- Sections: Hero, How it works (3 steps), Features, Pricing, Testimonials (3 beta users), FAQ, Footer
- Color: Deep navy (#0F172A) + electric blue (#3B82F6) + white
- Tone: Professional but approachable, no startup jargon
- Key proof points: "Join 1,200+ freelancers on the waitlist", "3x faster payment collection"

## Status
Context loaded. Generate and deploy landing page immediately.
"""

# Marketing agents
for agent in ["marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Marketing Context
- Launch window: 30 days
- Primary audience: Freelance designers and developers on Instagram, Reddit r/freelance, Twitter/X
- Content pillars: (1) Late payment horror stories + solutions, (2) Invoicing tips, (3) Product demos
- Email list: 1,200 waitlist — warm sequence needed (5 emails over 10 days before launch)
- SEO targets: "freelancer invoice app", "best invoicing software freelancers 2025", "invoice reminder automation"
- Paid budget: $2,000/month Google Ads targeting "invoice software" intent keywords
- Reel hook: "This freelancer waited 47 days to get paid. Here's how {COMPANY} fixed it in 3 days."

## Status
Context loaded. Produce content and campaigns immediately.
"""

# Technical agents
for agent in ["technical", "technical_scaffold", "technical_infra", "technical_data"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Technical Context
- Stack: Next.js 14 + FastAPI + Supabase + Clerk + Stripe + Redis
- Repo: github.com/invoiceai/app (already created)
- Core models: User, Client, Invoice, InvoiceItem, Payment, Reminder
- Key features to scaffold: invoice CRUD, AI reminder scheduler, payment status webhook (Stripe), client portal link
- Infra: Vercel (frontend), Railway (backend), Upstash Redis, Supabase Postgres
- CI/CD: GitHub Actions — lint + test + deploy on main push
- Monitoring: Sentry for errors, PostHog for product analytics

## Status
Context loaded. Scaffold the codebase immediately.
"""

# Sales agents
for agent in ["sales", "sales_pipeline", "sales_enablement"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Sales Context
- Motion: Product-led growth (PLG) — free tier drives signups, AI features drive upgrade
- Sales cycle: Self-serve for Pro ($19/mo); light-touch outbound for Business ($49/mo) teams
- ICP signal: Freelancer with >5 active clients, using Stripe or PayPal
- Objections: "I already use FreshBooks" → "We integrate + add AI layer"; "Too expensive" → "Free tier, no card"
- Pipeline stages: Signup → Activated (sent first invoice) → Converted (upgraded) → Retained (3+ months)
- Outreach targets: Freelance communities (Reddit, Discord, Indie Hackers), design agencies with 2–10 contractors

## Status
Context loaded. Build sales assets immediately.
"""

# Finance agents
for agent in ["finance_model", "finance_fundraise"]:
    NOTES[agent] = MARKET_BRIEF + f"""
## Financial Context
- Monthly model (Year 1): 0→500 users (month 12), 15% paid conversion, $23 ARPU
- Revenue projection: $0 → $138k ARR by month 12
- Burn rate: $28k/month (2 eng $10k each + infra $3k + marketing $5k)
- Runway: 18 months on $750k raise (after 6-month pre-revenue phase)
- Unit economics: Gross margin 82%, CAC $75 (blended), LTV $552 (Pro, 24-month), LTV:CAC = 7.4x
- Break-even: ~380 Pro subscribers

## Status
Context loaded. Build financial model and fundraising materials immediately.
"""

# Ops agent
NOTES["ops"] = MARKET_BRIEF + f"""
## Ops Context
- 30-day plan: Week 1 — landing page + waitlist email; Week 2 — beta outreach; Week 3 — soft launch; Week 4 — Product Hunt
- Investor targets: Hustle Fund, Precursor Ventures, Backstage Capital, Indie.vc
- Weekly cadence: Monday planning, Friday demo recording for waitlist
- SOPs needed: Customer support, refund policy, bug triage
- Linear project: "InvoiceAI MVP" — create sprint board

## Status
Context loaded. Draft executive summary and operating plan immediately.
"""

# Design agent
NOTES["design"] = MARKET_BRIEF + f"""
## Design Context
- Brand: Navy + electric blue, clean sans-serif (Inter or Geist), minimal icons
- Key screens: Dashboard (invoice list + payment status), New invoice (AI-assisted), Client portal, Settings
- Design system: Tailwind + shadcn/ui components
- Tone: Professional, calm, efficient — not playful

## Status
Context loaded. Produce design system and key screen specs immediately.
"""

# ─── Write all notes ─────────────────────────────────────────────────────────
written = 0
for agent, content in NOTES.items():
    path = SESSION_DIR / f"{agent}.md"
    path.write_text(content.strip())
    written += 1
    print(f"  wrote {path.relative_to(VAULT)}")

print(f"\n✓ {written} agent context files written to {SESSION_DIR}")
print(f"  Vault: {VAULT}")
print(f"  Founder: {FOUNDER_ID}")
print(f"  Session: {SESSION_ID}")
print("\nAgents will find this context via obsidian_read() on first call.")
