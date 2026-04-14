# Troopod — AI Landing Page Personalizer

Upload an ad creative + a landing page URL → get that same landing page, enhanced in-place to match the ad's offer, tone, and visuals, with CRO best practices applied. Refine via a chat agent. Powered by a multi-agent Agno pipeline with web-vision tools from Agent-Reach.

## Monorepo layout

```
/api         Python FastAPI + Agno multi-agent backend  (Railway)
/web         Next.js + TypeScript + Tailwind frontend   (Vercel)
/supabase    Postgres schema, migrations, storage       (Supabase)
/docs        Design.md per agent + robustness writeup
```

## Core principle (from the assignment)

The generated page is **never a new page** — it is the user's existing landing page, patched in place (same layout, same assets). Agents produce a structured **Patch Plan**, applied as DOM surgery on the scraped HTML.

## Agents

1. **Extractor** — reads the ad (Gemini vision) and the page (Playwright + Jina Reader) → structured profiles.
2. **Strategist** — merges profiles + CRO principles → structured Patch Plan.
3. **Builder** — applies the patch to the real DOM (BeautifulSoup), preserving layout.
4. **Verifier** — screenshots the rendered result, checks layout integrity + hallucination-free claims, loops back.
5. **Refiner (Chat)** — handles user follow-ups live via Supabase Realtime.

See `/docs/design/*` for per-agent specs.

## Local dev

See `/api/README.md` and `/web/README.md`.
