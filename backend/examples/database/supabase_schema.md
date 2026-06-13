---
title: Supabase Schema + Row Level Security Patterns
tags: [database, supabase, postgres, rls, schema]
category: database
applies_to: [technical, technical_scaffold, technical_data]
---

# Supabase Schema Patterns

## SaaS starter schema (SQL)
```sql
-- Users table (mirrors auth.users)
create table public.profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  email text unique not null,
  name text,
  plan text default 'free' check (plan in ('free', 'pro', 'enterprise')),
  created_at timestamptz default now()
);

-- Auto-create profile on sign-up
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id, email, name)
  values (new.id, new.email, new.raw_user_meta_data->>'name');
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Resources owned by a user
create table public.projects (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references public.profiles(id) on delete cascade not null,
  name text not null,
  data jsonb default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- RLS: users can only see their own data
alter table public.profiles enable row level security;
alter table public.projects enable row level security;

create policy "Users can view own profile"
  on public.profiles for select using (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update using (auth.uid() = id);

create policy "Users can CRUD own projects"
  on public.projects for all using (auth.uid() = user_id);
```

## Querying from Next.js server component
```typescript
import { createClient } from "@/lib/supabase/server";

export default async function ProjectsPage() {
  const supabase = await createClient();
  const { data: projects, error } = await supabase
    .from("projects")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) throw error;
  return <ul>{projects.map(p => <li key={p.id}>{p.name}</li>)}</ul>;
}
```

## Inserting data
```typescript
const { data, error } = await supabase
  .from("projects")
  .insert({ name: "My Project", user_id: user.id })
  .select()
  .single();
```

## Realtime subscription (client component)
```typescript
"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

export function LiveProjects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const supabase = createClient();

  useEffect(() => {
    const channel = supabase
      .channel("projects")
      .on("postgres_changes", { event: "*", schema: "public", table: "projects" },
        (payload) => {
          if (payload.eventType === "INSERT") setProjects(p => [payload.new as Project, ...p]);
          if (payload.eventType === "DELETE") setProjects(p => p.filter(x => x.id !== payload.old.id));
        }
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, []);

  return <ul>{projects.map(p => <li key={p.id}>{p.name}</li>)}</ul>;
}
```

## Notes
- Always enable RLS on every table — Supabase is public by default without it
- Use `gen_random_uuid()` for IDs (Postgres built-in, no extension needed)
- Use `security definer` on trigger functions so they run as postgres superuser
