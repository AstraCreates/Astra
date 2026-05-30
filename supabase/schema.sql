create extension if not exists "pgcrypto";

create table founders (
  id          uuid primary key default gen_random_uuid(),
  email       text unique not null,
  plan        text not null default 'launch',
  credit_balance integer not null default 0,
  created_at  timestamptz not null default now()
);

create table goals (
  id              text primary key,
  founder_id      uuid not null references founders(id),
  instruction     text not null,
  status          text not null default 'pending',
  constraints     jsonb default '{}',
  elapsed_seconds float,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

create table tasks (
  id               text primary key,
  goal_id          text not null references goals(id),
  founder_id       uuid not null references founders(id),
  agent            text not null,
  instruction      text not null,
  context_bundle   jsonb default '{}',
  depends_on       text[] not null default '{}',
  tools_available  text[] not null default '{}',
  constraints      jsonb default '{}',
  status           text not null default 'pending',
  result           jsonb,
  approval_required boolean not null default false,
  created_at       timestamptz not null default now(),
  completed_at     timestamptz
);

create table approvals (
  id              uuid primary key default gen_random_uuid(),
  task_id         text not null references tasks(id),
  founder_id      uuid not null references founders(id),
  agent           text not null,
  action          text not null,
  consequence     text not null,
  documents_ready text[] default '{}',
  approval_token  text unique not null,
  expires_at      timestamptz not null,
  approved_at     timestamptz,
  rejected_at     timestamptz,
  reject_reason   text,
  created_at      timestamptz not null default now()
);

create table memory_documents (
  id          uuid primary key default gen_random_uuid(),
  founder_id  uuid not null references founders(id),
  namespace   text not null,
  agent       text not null,
  task_id     text references tasks(id),
  doc_type    text not null,
  content     text not null,
  summary     text not null,
  metadata    jsonb default '{}',
  created_at  timestamptz not null default now()
);

create index on tasks(goal_id, status);
create index on memory_documents(founder_id, namespace);

create table founder_credentials (
  id               uuid primary key default gen_random_uuid(),
  founder_id       uuid not null references founders(id),
  service          text not null,
  encrypted_creds  text not null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (founder_id, service)
);

create index on founder_credentials(founder_id);

-- Generic durable document mirror for local-first platform state.
-- Backend storage_adapter.py writes accounts, run ledgers, workflow snapshots,
-- Company Brain stores, and approval ledgers here when ASTRA_STORAGE_BACKEND is
-- set to `supabase` or `dual`.
create table if not exists astra_documents (
  collection text not null,
  key        text not null,
  payload    jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (collection, key)
);

create index if not exists astra_documents_collection_updated_idx
  on astra_documents(collection, updated_at desc);

-- ── Outreach tool ──────────────────────────────────────────────────────────────

create table if not exists outreach_contacts (
  id               uuid primary key default gen_random_uuid(),
  founder_id       text not null,
  email            text not null,
  first_name       text not null default '',
  last_name        text not null default '',
  title            text not null default '',
  company_name     text not null default '',
  company_domain   text not null default '',
  linkedin_url     text not null default '',
  city             text not null default '',
  state            text not null default '',
  country          text not null default '',
  industry         text not null default '',
  company_size     text not null default '',
  funding_stage    text not null default '',
  seniority        text not null default '',
  apollo_id        text,
  source           text not null default 'apollo',
  status           text not null default 'new',
  tags             text[] not null default '{}',
  enriched_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists outreach_contacts_founder_status on outreach_contacts(founder_id, status);
create index if not exists outreach_contacts_apollo_id on outreach_contacts(apollo_id) where apollo_id is not null;
create unique index if not exists outreach_contacts_founder_email on outreach_contacts(founder_id, email);

create table if not exists outreach_lists (
  id             uuid primary key default gen_random_uuid(),
  founder_id     text not null,
  name           text not null,
  description    text not null default '',
  filters        jsonb not null default '{}',
  contact_count  int not null default 0,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists outreach_lists_founder on outreach_lists(founder_id);

create table if not exists outreach_list_members (
  list_id     uuid not null references outreach_lists(id) on delete cascade,
  contact_id  uuid not null references outreach_contacts(id) on delete cascade,
  added_at    timestamptz not null default now(),
  primary key (list_id, contact_id)
);
create index if not exists outreach_list_members_list on outreach_list_members(list_id);

create table if not exists outreach_campaigns (
  id               uuid primary key default gen_random_uuid(),
  founder_id       text not null,
  name             text not null,
  from_name        text not null default '',
  from_email       text not null default '',
  reply_to         text not null default '',
  status           text not null default 'draft',
  send_provider    text not null default 'sendgrid',
  steps            jsonb not null default '[]',
  product_name     text not null default '',
  value_prop       text not null default '',
  daily_limit      int not null default 50,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists outreach_campaigns_founder_status on outreach_campaigns(founder_id, status);

create table if not exists outreach_campaign_contacts (
  id                 uuid primary key default gen_random_uuid(),
  campaign_id        uuid not null references outreach_campaigns(id) on delete cascade,
  contact_id         uuid not null references outreach_contacts(id),
  founder_id         text not null,
  status             text not null default 'pending',
  current_step       int not null default 0,
  next_send_at       timestamptz,
  last_sent_at       timestamptz,
  personalized_steps jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (campaign_id, contact_id)
);
create index if not exists outreach_cc_campaign_status on outreach_campaign_contacts(campaign_id, status);
create index if not exists outreach_cc_next_send on outreach_campaign_contacts(next_send_at) where status = 'active';

create table if not exists outreach_email_events (
  id                   uuid primary key default gen_random_uuid(),
  founder_id           text not null,
  campaign_id          uuid references outreach_campaigns(id),
  campaign_contact_id  uuid references outreach_campaign_contacts(id),
  contact_id           uuid references outreach_contacts(id),
  event_type           text not null,
  step_index           int not null default 0,
  url                  text,
  metadata             jsonb default '{}',
  occurred_at          timestamptz not null default now()
);
create index if not exists outreach_events_campaign on outreach_email_events(campaign_id, event_type);
create index if not exists outreach_events_founder_time on outreach_email_events(founder_id, occurred_at desc);
