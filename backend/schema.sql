-- ============================================================
-- Multi-Agent LLM Data Analysis System — Supabase Schema
-- Run this entire file in the Supabase SQL Editor (single paste)
-- ============================================================

-- Enable UUID generation (already enabled on Supabase, but safe to run)
create extension if not exists "pgcrypto";

-- ============================================================
-- TABLE: sessions
-- Created once per browser session. Ties uploads + messages together.
-- ============================================================
create table if not exists sessions (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz default now(),
  user_agent  text
);

-- ============================================================
-- TABLE: uploads
-- One row per CSV file uploaded in a session.
-- col_names, dtypes, sample_rows stored as JSONB for flexibility.
-- ============================================================
create table if not exists uploads (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid references sessions(id) on delete cascade,
  filename     text not null,
  row_count    int,
  col_names    jsonb,
  dtypes       jsonb,
  sample_rows  jsonb,
  created_at   timestamptz default now()
);

-- ============================================================
-- TABLE: messages
-- One row per question asked. Stores the full agent output.
-- chart_b64 can be large — Supabase supports up to 1GB text cols.
-- ============================================================
create table if not exists messages (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid references sessions(id) on delete cascade,
  upload_id     uuid references uploads(id),
  question      text,
  final_report  text,
  chart_b64     text,
  eval_score    float,
  iterations    int,
  created_at    timestamptz default now()
);

-- ============================================================
-- INDEXES — speed up history lookups by session
-- ============================================================
create index if not exists idx_uploads_session_id  on uploads(session_id);
create index if not exists idx_messages_session_id on messages(session_id);
create index if not exists idx_messages_upload_id  on messages(upload_id);

-- ============================================================
-- ROW LEVEL SECURITY — optional but recommended
-- Disable for now during development; enable before production
-- ============================================================
alter table sessions disable row level security;
alter table uploads  disable row level security;
alter table messages disable row level security;

-- ============================================================
-- VERIFICATION QUERY — run after migration to confirm tables exist
-- ============================================================
select
  table_name,
  (select count(*) from information_schema.columns
   where table_name = t.table_name
   and table_schema = 'public') as column_count
from information_schema.tables t
where table_schema = 'public'
  and table_name in ('sessions', 'uploads', 'messages')
order by table_name;
