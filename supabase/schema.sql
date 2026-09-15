-- CivicLens starter schema
-- Run in the Supabase SQL editor when the released hackathon data arrives.

create extension if not exists pgcrypto;

create table if not exists public.businesses (
  id uuid primary key default gen_random_uuid(),
  enterprise_number text,
  establishment_number text,
  name text not null,
  street text,
  house_number text,
  postcode text,
  municipality text,
  activity text,
  nace_code text,
  status text,
  source text,
  source_updated_at timestamptz,
  confidence integer check (confidence between 0 and 100),
  raw_data jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists businesses_name_idx on public.businesses (name);
create index if not exists businesses_municipality_idx on public.businesses (municipality);
create index if not exists businesses_enterprise_number_idx on public.businesses (enterprise_number);

alter table public.businesses enable row level security;

-- Suitable only for public/demo data. Tighten this if released data is sensitive.
drop policy if exists "Public demo read" on public.businesses;
create policy "Public demo read"
on public.businesses
for select
to anon
using (true);
