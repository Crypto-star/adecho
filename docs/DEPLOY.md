# Deployment — Troopod

Production targets: **Railway** (API, Docker) + **Vercel** (Web, Next.js) + **Supabase** (DB, Storage, Realtime).

---

## 1. Supabase — one-time setup

1. Create a project at [supabase.com](https://supabase.com).
2. Copy **Project URL**, **anon** key, **service_role** key from Project Settings → API.
3. SQL editor → run both migrations in order:
   ```sql
   -- 0001_init.sql — tables, RLS, publication
   -- 0002_page_profile.sql — adds ad_extracts.page_profile jsonb column
   ```
4. Storage → create three **private** buckets:
   - `ad-uploads`
   - `screenshots`
   - `patched-html`
5. Database → Replication → ensure `supabase_realtime` publication includes
   `chat_messages`, `renders`, `sessions`.

---

## 2. Railway — API deployment

### Option A: Connect the repo (recommended)

1. New project → **Deploy from GitHub repo** → pick this repo.
2. **Root directory:** `api`
3. Railway auto-detects `railway.toml` + `Dockerfile`.
4. Add environment variables (Settings → Variables):

   ```env
   OPENAI_API_KEY=sk-...
   GOOGLE_API_KEY=AIza...
   EXA_API_KEY=...
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   SUPABASE_ANON_KEY=eyJ...
   CORS_ORIGINS=https://<your-vercel-domain>.vercel.app
   LOG_TO_STDOUT=1                       # optional; auto-enabled on Railway
   ```

5. Deploy. First build ≈ 3-4 min (Playwright image warm-up). Subsequent < 90s.
6. Health-check: `GET <RAILWAY_URL>/health` → `{ "ok": true }`.

### Option B: CLI

```bash
npm i -g @railway/cli
railway login
cd api
railway link
railway up
```

Railway will read `railway.toml` and build the Dockerfile. Inject env vars via
`railway variables --set KEY=value` or the dashboard.

### Health, logs, scaling

- Healthcheck path: `/health` (set in `railway.toml`).
- Logs: captured from stdout — `railway logs`. `LOG_TO_STDOUT=1` is set inside
  the Dockerfile; loguru streams there instead of to a file.
- Cold boot: Playwright image is ~1 GB; start-up after build ≈ 3 s.
- Scaling: pipeline is I/O-bound — a single replica handles dozens of
  concurrent sessions. For more, bump `numReplicas` in `railway.toml`.

### Why the Playwright base image?

`mcr.microsoft.com/playwright/python:v1.58.0-noble` already has Chromium +
every shared lib (libnss3, libatk, libdrm, libgbm, …) pre-installed. Building
these into a slim-python image reliably takes 5-8 minutes per cold start.
The tradeoff: larger image (~1 GB). Acceptable for a long-running service.

---

## 3. Vercel — Web deployment

1. **New project** → import the same GitHub repo.
2. **Root directory:** `web`
3. Framework preset: Next.js (auto-detected from `vercel.json`).
4. Environment variables:

   ```env
   NEXT_PUBLIC_API_BASE_URL=https://<your-railway-app>.up.railway.app
   NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
   ```

5. Deploy. After first deploy, copy the Vercel domain back to Railway's
   `CORS_ORIGINS` env var.

`next.config.mjs` rewrites `/api/*` → `${NEXT_PUBLIC_API_BASE_URL}/*` so the
FE talks to the Railway backend transparently.

---

## 4. Post-deploy smoke test

1. Open `<VERCEL_URL>`.
2. Upload `samples/ad_linear.png` + URL `https://linear.app`.
3. Wait ~60s; personalized page should appear.
4. Toggle **Original ↔ Personalized**.
5. Chat: *"Make the hero background purple."* → chat updates within 3s (optimistic + polling), assistant reply within ~60s (background critic loop).
6. Railway logs (`railway logs`) should show:
   ```
   Extractor done for session <uuid>
   Builder v1 applied=1 skipped=0
   Verifier v1 passed=True
   Critic v1 score=X verdict=ship
   ```

---

## 5. Known operational notes

- **Supabase Realtime** may show `CHANNEL_ERROR` / `TIMED_OUT` in some browsers
  (Safari, corporate VPNs). The FE has a 3-second polling fallback so chat
  still works.
- **SSRF:** the scraper accepts any user-provided URL. For production, add a
  scheme+IP check (reject `file://`, `data:`, RFC-1918 / loopback / link-local
  addresses). Intentionally omitted for the demo.
- **Secrets:** don't commit `.env` files. Confirm `git log --all -- api/.env`
  shows nothing before pushing to a public repo.

---

## 6. Rollback

- Railway: Deployments tab → pick a prior healthy deploy → **Redeploy**.
- Vercel: Deployments → promote any earlier deploy to Production.
- Supabase: migrations are additive; `0002_page_profile.sql` can be reverted
  with `alter table ad_extracts drop column page_profile;` if needed.
