-- Troopod initial schema
-- Run via: supabase db push   (or paste into SQL editor)

create extension if not exists "uuid-ossp";

-- Sessions ---------------------------------------------------------------
create table if not exists sessions (
  id              uuid primary key default uuid_generate_v4(),
  ad_path         text,              -- supabase storage path in bucket `ad-uploads`
  landing_url     text not null,
  status          text not null default 'created'
                  check (status in ('created','extracting','strategizing',
                                    'building','verifying','ready','failed')),
  error           text,
  current_version int  not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Agent outputs (one row per stage per version) -------------------------
create table if not exists scrapes (
  session_id      uuid references sessions(id) on delete cascade,
  html            text,
  markdown        text,
  screenshot_path text,
  palette         jsonb,
  created_at      timestamptz not null default now(),
  primary key (session_id)
);

create table if not exists ad_extracts (
  session_id      uuid references sessions(id) on delete cascade,
  profile         jsonb not null,
  brand_context   jsonb,
  created_at      timestamptz not null default now(),
  primary key (session_id)
);

create table if not exists patch_plans (
  session_id      uuid references sessions(id) on delete cascade,
  version         int  not null,
  plan            jsonb not null,
  created_at      timestamptz not null default now(),
  primary key (session_id, version)
);

create table if not exists renders (
  session_id      uuid references sessions(id) on delete cascade,
  version         int  not null,
  patched_html    text not null,
  screenshot_path text,
  created_at      timestamptz not null default now(),
  primary key (session_id, version)
);

create table if not exists verifier_reports (
  session_id      uuid references sessions(id) on delete cascade,
  version         int  not null,
  passed          bool not null,
  issues          jsonb not null default '[]',
  screenshot_path text,
  created_at      timestamptz not null default now(),
  primary key (session_id, version)
);

-- Chat (refiner) --------------------------------------------------------
create table if not exists chat_messages (
  id           bigserial primary key,
  session_id   uuid references sessions(id) on delete cascade,
  role         text not null check (role in ('user','assistant','system')),
  content      text not null,
  plan_version int,
  created_at   timestamptz not null default now()
);
create index if not exists chat_messages_session_idx on chat_messages(session_id, created_at);

-- Agent observability ---------------------------------------------------
create table if not exists agent_logs (
  id          bigserial primary key,
  session_id  uuid references sessions(id) on delete cascade,
  agent       text not null,
  version     int,
  input       jsonb,
  output      jsonb,
  elapsed_ms  int,
  error       text,
  created_at  timestamptz not null default now()
);
create index if not exists agent_logs_session_idx on agent_logs(session_id, created_at);

-- Realtime --------------------------------------------------------------
-- Enable Realtime on these tables via the Supabase dashboard (or):
alter publication supabase_realtime add table sessions, chat_messages,
       renders, verifier_reports, agent_logs;

-- Storage buckets -------------------------------------------------------
-- Create in Supabase dashboard (or via CLI):
--   ad-uploads   (private, authenticated read)
--   screenshots  (private)
--   patched-html (private)

-- RLS (minimal; tighten in prod) ---------------------------------------
alter table sessions          enable row level security;
alter table chat_messages     enable row level security;
alter table renders           enable row level security;
alter table verifier_reports  enable row level security;
alter table agent_logs        enable row level security;

-- For the demo we allow anon read of session artifacts and anon insert of chat.
-- Service role (backend) bypasses RLS.
create policy "anon read sessions"         on sessions          for select to anon using (true);
create policy "anon read chat"             on chat_messages     for select to anon using (true);
create policy "anon insert chat"           on chat_messages     for insert to anon with check (role = 'user');
create policy "anon read renders"          on renders           for select to anon using (true);
create policy "anon read verifier_reports" on verifier_reports  for select to anon using (true);
create policy "anon read agent_logs"       on agent_logs        for select to anon using (true);
