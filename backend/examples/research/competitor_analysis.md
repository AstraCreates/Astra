---
title: Competitor Analysis Framework — Market Research Template
tags: [research, competitor, market, analysis, framework]
category: research
applies_to: [research, research_market, research_financial, research_regulatory]
---

# Competitor Analysis Framework

## Structure for every competitor analysis

### 1. Landscape map
```
Direct competitors:    same ICP, same problem, same solution category
Indirect competitors:  same ICP, same problem, different approach (e.g. hiring a person vs software)
Substitutes:           different solution, same budget line (e.g. spreadsheet vs SaaS)
```

### 2. Per-competitor card
```
Company:        {name} — {one-line description}
Founded:        {year}  |  Funding: {stage + amount or "bootstrapped"}
Team size:      {approx, from LinkedIn}
Pricing:        {free tier?} | {entry plan: $/mo} | {mid: $/mo} | {enterprise: custom?}
ICP:            {company size} + {industry/role}
Core feature:   {what they're known for}
Weakness:       {from G2/Capterra/Reddit reviews — real pain points}
Traction signal: {G2 reviews count, App Store rating, estimated traffic from SimilarWeb}
```

### 3. Differentiation matrix
| Feature/Attribute | Us | Competitor A | Competitor B |
|---|---|---|---|
| {feature 1} | ✓ | ✗ | ✓ |
| {feature 2} | ✓ | ✓ | ✗ |
| {price: $/mo} | $X | $Y | $Z |
| {free tier} | ✓ | ✗ | ✗ |

### 4. Pricing positioning
```
Budget:   ${low} - ${mid}    → target: {who}
Mid:      ${mid} - ${high}   → target: {who}
Premium:  ${high}+           → target: {who}
```

### 5. Market gaps (what nobody does well)
- {gap 1}: {evidence from reviews/forums}
- {gap 2}: {evidence}
- {gap 3}: {evidence}

### 6. Sources to research
- G2.com/{category} — real user reviews, feature comparisons, pricing
- Reddit r/{relevant_subreddit} — candid user pain points
- Hacker News "Ask HN" threads — technical audience perspective
- SimilarWeb — traffic estimates
- LinkedIn — team size, recent hires signal growth areas
- Crunchbase — funding history
- Their changelog/blog — what they're shipping

## Output format (for research report)
```markdown
## Competitive Landscape: {market}

**Market size**: {TAM estimate} — {source}

### Competitors
{3-5 competitor cards from template above}

### Differentiation matrix
{table}

### Market gaps we target
{3 gaps with evidence}

### Pricing recommendation
Position at ${X}/mo — {rationale based on competitor map}
```

## Research quality rules
- NEVER invent testimonials, revenue figures, or user counts
- Cite source for every data point (G2, SimilarWeb, Crunchbase, etc.)
- Use "estimated" or "approx" when data is from public inference
- Competitor weakness = from actual user reviews, not assumptions
