# Troopod Web

Next.js 15 frontend. Landing page + split-view session page (chat left, rendered iframe right).

## Dev

```bash
cd web
cp ../.env.example .env.local   # fill NEXT_PUBLIC_* keys
npm install
npm run dev
```

Backend must run at `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`). All `/api/*` calls are rewritten to the Python backend (see `next.config.mjs`).
