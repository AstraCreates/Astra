# Mockup Frontend Redesign — Merge Notes

## What this branch contains

A **static HTML/CSS/JS mockup** of a fully redesigned Astra frontend. It lives entirely inside `mockup/` and has **zero changes to the real Next.js frontend** (`frontend/`). It is served via a simple Python HTTP server on port 5555 for local testing.

The goal of this redesign was to validate a new UX direction before touching the production app. Once approved, the mockup should be ported into the real Next.js + React frontend.

---

## Design language

| Token | Value |
|---|---|
| Primary blue | `#2b45ff` |
| Font — headings | Chakra Petch (700/600) |
| Font — body/mono | IBM Plex Mono (400/500) |
| Corners | Square (0px radius everywhere) |
| Theme | Light mode, white surfaces |
| Background | `#eeeeee` |

All CSS variables are in the `<style>` block at the top of `mockup/app/index.html`.

---

## Architecture

### Single-page app (`mockup/app/index.html`)

One HTML file replaces three separate pages. Uses hash-based routing (`#/`, `#/new`, `#/session/:id`).

**Three views rendered inside `#view`:**
- `#v-dash` — Dashboard: lists all sessions for the current user
- `#v-new` — New Goal: goal textarea + optional company name + stack selector
- `#v-sess` — Session: live agent monitoring, approval cards, artifact vault

### Auth

Same localStorage key as the real Next.js frontend: `astra_dev_user_id`.

- Anonymous users: auto-generated `user_XXXX` ID (UUID-based, same logic as `frontend/lib/use-dev-user.ts`)
- Google-signed-in users: `google_email_at_domain_com` format (decoded from GIS JWT)
- Google sign-in via Google Identity Services (`accounts.google.com/gsi/client`)
- Client ID: `642840461553-96ocfhlv3q190t3abg0f91a8r5n404qr.apps.googleusercontent.com`

All backend requests send `x-astra-user-id: founderId` header. The backend trusts this header when `astra_require_auth=False` (default for local dev).

### Backend wiring (all at `http://localhost:8000`)

| Action | Endpoint | Notes |
|---|---|---|
| List sessions | `GET /sessions?founder_id=X` | Returns `{sessions:[{session_id, goal, status, created_at, ...}]}` |
| Load session state | `GET /sessions/{id}/state` | May 404 for errored sessions — handled gracefully |
| Live events | `GET /stream/{id}` (SSE) | EventSource, auto-reconnects |
| Submit goal | `POST /goal` | Body: `{founder_id, instruction, stack_id?}` |
| List stacks | `GET /stacks` | Returns `{stacks:[{stack_id, name, description, agents:[]}]}` — field is `stack_id` NOT `id` |
| Approve/reject | `POST /stack/approval` | Body: `{session_id, gate_key, decision, founder_id}` |
| Steer agents | `POST /steer/{session_id}` | Body: `{message}` |
| Stop run | `POST /sessions/{id}/kill` | |

### Key data shape notes (for porting to React)

**State endpoint** (`GET /sessions/{id}/state`) does NOT include a `goal` field. The goal must be fetched from the sessions list endpoint first.

```js
// Correct pattern:
const list = await fetch('/sessions?founder_id=X').then(r=>r.json());
const meta = list.sessions.find(s => s.session_id === id); // has .goal
const state = await fetch(`/sessions/${id}/state`).then(r=>r.json()); // no .goal
```

**Stacks** use `stack_id` not `id`:
```js
// Correct: s.stack_id || s.id
// Wrong:   s.id  ← always undefined
```

**Agent shape** from state (camelCase):
```js
{
  status: "waiting"|"running"|"done"|"error",
  log: [{ts: number, type: string, text: string}],
  visitedUrls: string[],
  currentTool: string|null,
  result: string|null,
  instruction: string,
}
```

**Approval SSE event** — the request is nested:
```js
// ev.type === "approval_request"
// ev.request = { gate_key, title, reason, agent, action_id, ... }
const raw = ev.request || ev;  // normalize — state approvals are flat, SSE approvals are nested
const gate_key = raw.gate_key || raw.key || ev.approval_gate;
```

**Pending approval statuses** to show: `pending`, `triggered`, `armed`, `waiting_approval`.

**Artifact SSE** — nested in `ev.artifact`, flat in state:
```js
const art = ev.artifact || ev;
```

---

## Session view layout

```
┌─ Nav (200px) ─┬─────────────── Main ────────────────────────────┐
│               │  Topbar (goal title, status pill, stop button)   │
│  Logo         ├──────────────────────────────────────────────────┤
│  + New goal   │  [URGENT BANNER — red, when approval pending]    │
│               ├──────────────────────────────────────────────────┤
│  Dashboard    │  Phase bar (Planning → Execution → Complete)     │
│  Outreach     ├──────────────────────────────────────────────────┤
│  Brain        │  Status bar (live agent counts)                  │
│  ──────────   ├──────────────────────────────────────────────────┤
│  Integrations │  Dept cards (Research, Design, Technical, …)     │
│  Payments     ├──────────────┬───────────────────────────────────┤
│               │  Vault       │  Detail panel                     │
│  ──────────   │  (artifact   │  (tabs: What happened / Sources)  │
│  Settings     │   list)      │  Approval cards appear here first │
│  User/Google  │              │  Agent log / artifact preview     │
└───────────────┴──────────────┴───────────────────────────────────┘
                │           Steer bar (send instructions)          │
                └──────────────────────────────────────────────────┘
```

### Department groupings (maps agents → UI cards)

```js
const DEPTS = {
  research:  {n:'Research',  ags:['research','research_competitors','research_market',...]},
  design:    {n:'Design',    ags:['design']},
  technical: {n:'Technical', ags:['technical','technical_scaffold','web','web_navigator',...]},
  marketing: {n:'Marketing', ags:['marketing','marketing_content','marketing_outreach',...]},
  legal:     {n:'Legal',     ags:['legal','legal_docs','legal_entity','legal_ip']},
  sales:     {n:'Sales',     ags:['sales','sales_pipeline','ops']},
  finance:   {n:'Finance',   ags:['finance_model','finance_fundraise']},
};
```

---

## Approval flow

1. Backend publishes `approval_request` SSE event (nested under `ev.request`)
2. Frontend normalizes it, deduplicates by `gate_key`, adds to `S.approvals`
3. Urgent banner appears at top of main area
4. Approval card rendered at top of detail panel
5. User clicks Approve/Skip/Reject → `POST /stack/approval`
6. On success: `gate_key` added to `S.decidedKeys` (a `Set`), card removed
7. SSE replay protection: `approval_request` events ignored if `gate_key` is in `decidedKeys`
8. Backend publishes `stack_approval_decision` → frontend also adds to `decidedKeys`

---

## New goal form

Fields:
1. **Company/Project name** (optional) — prepended to instruction as `Company/project name: {name}\n\n{goal}`
2. **Goal** (textarea, min 10 chars)
3. **Stack selector** — loads from `GET /stacks`, uses `stack_id` field

On submit → `POST /goal` with `{founder_id, instruction, stack_id?}` → redirects to `#/session/{session_id}`.

---

## Files to port into Next.js

When merging, the real Next.js components that should be updated to match this design:

| Real file | What to match from mockup |
|---|---|
| `frontend/components/GoalWorkspace.tsx` | Session view layout, dept cards, approval cards, vault |
| `frontend/components/PhaseWorkboard.tsx` | Phase bar + status bar |
| Dashboard page | Sessions grid cards |
| New goal page | Company name field + stack selector fix (`stack_id` not `id`) |

**Important**: The real frontend uses NextAuth v5 for auth, not GIS. Do NOT copy the Google sign-in code — that's only for the mockup. The user ID format (`google_email_at_domain_com`) must match between both.

---

## How to run the mockup locally

```bash
cd mockup
python -m http.server 5555
# then open http://localhost:5555/app/index.html
# backend must be running on port 8000
```

---

## What is NOT in this branch

- No changes to `frontend/` (Next.js app)
- No changes to `backend/` (FastAPI)
- No database migrations
- No env var changes
