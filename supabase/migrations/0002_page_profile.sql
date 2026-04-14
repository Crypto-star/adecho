-- Persist the extractor's PageProfile so the Refiner has real selectors to
-- work with when a chat message arrives after the original run.
alter table ad_extracts
  add column if not exists page_profile jsonb not null default '{}'::jsonb;
