# Troopod — AI PM Assignment Submission

Subject: `Assignment AI PM - Troopod`
Send to: `nj@troopod.io`

**Live demo:** `<FE_URL>` · **Repo:** `<REPO_URL>` · **API:** `<API_URL>/health`

---

## 1. What it does

A user uploads an **ad creative** and pastes a **landing page URL**. Troopod returns **that same landing page, enhanced in-place** to match the ad's offer, tone, and visuals, with CRO best practices applied. A chat pane lets the user refine live. Toggle **Original ↔ Personalized** to compare.

> **The core constraint from the brief:** the personalized page is never a new page. It's the user's original HTML, patched. Every agent operates on the scraped DOM.

---

## 2. How it works (flow)

```
┌──────────────────────────────────────────────────────────────┐
│  For every turn — initial run AND every chat refinement:     │
│                                                              │
│  user_instruction  ──►  Strategist                           │
│                         (fresh full PatchPlan, not delta)    │
│                         │                                    │
│                         ▼                                    │
│                      Builder  (DOM surgery, deterministic)   │
│                         │                                    │
│                         ▼                                    │
│                     Verifier  (rule checks)                  │
│                         │                                    │
│                         ▼                                    │
│                       Critic  (vision — ad vs. result)       │
│                         │                                    │
│                         ▼                                    │
│                    ship | refine  (≤2 refine loops)          │
└──────────────────────────────────────────────────────────────┘
```

- **Initial run** (session creation): Extractor scrapes the page + analyses the ad, then drives the loop with `"Personalize this page for the ad"` as instruction.
- **Chat turn**: same loop, same critic gate, but `user_instruction` is the user's message and the Strategist also receives `CURRENT_PLAN`, `CHAT_HISTORY`, and a `PRESERVE_VERBATIM` block so prior personalization survives.
- **One codepath** for initial + refinements — no separate "refiner" agent. This eliminates an entire class of drift bugs where refinement quality lagged initial quality.

---

## 3. Key components / agent design

Each agent has a versioned `Design.md` (in `/docs/design/`) injected as system prompt. Every output is a Pydantic model validated before the next stage runs.

| Agent | Model | Primary tools | Output contract |
| ----- | ----- | ------------- | --------------- |
| **Extractor** | Gemini 2.5 Pro (vision) | Playwright (scrape + screenshot + computed-CSS tokens), Jina Reader (Agent-Reach), Exa (brand snippets) | `ExtractorOutput` — ad profile, page profile (stamped selectors + design tokens), brand context |
| **Strategist** | GPT-4.1 | Exa | `PatchPlan` — structured changes: selector → op → payload → source |
| **Builder** | — (pure code) | BeautifulSoup | `RenderArtifact` — patched HTML, selectors applied/skipped |
| **Verifier** | — (rule checks) | Playwright screenshot | `VerifierReport` — blocker/warn issues |
| **Critic** | Gemini 2.5 Pro (vision) | Playwright screenshot | `CriticReport` — score 1-10, issues, verdict: `ship | refine | rebuild` |

### Building blocks

- **Stamping.** Extractor walks the DOM, gives every addressable element a unique `data-troopod-id="tN"` attribute. All selectors downstream are `[data-troopod-id='tN']` — guaranteed to resolve to exactly one element.
- **Design tokens.** Extractor runs `getComputedStyle` in the browser to pull real fonts/colors/radius/shadow off the page. Strategist authors new HTML using these, so the personalized hero *looks like the user's brand*.
- **Block surgery.** Primary op is `replace_section` on the hero container — not `replace_text` on individual nodes — because text-level changes leave stale siblings visible on modern SSR sites (Linear's animation-layer h1s, for instance). When replacing a section, the Builder also strips any orphan `<h1>`s elsewhere.
- **Hero-container heuristic.** 5-tier selector: semantic landmark (`section`/`header`/`main`) > class-hint match (`hero|banner|landing|…`) > structural signature (has h1 + p + a/button) > sanity-checked common-ancestor > parent fallback. Tested against a synthetic Stripe-like DOM to prevent narrow-column rendering.
- **`PRESERVE_VERBATIM` on chat turns.** Before a refinement, we parse the current plan's `replace_section` payload and inject `{headline, subheadline, cta_text}` into the Strategist prompt as a strict preserve list. Prevents the model from regenerating the hero from Linear's own copy.

### One-sentence summary of decision-making

> The **ad** tells us *what* to say; the **page** tells us *where* and *how* to say it; **design tokens** make it look native; the **Strategist** stitches those into a plan; the **Builder** applies it deterministically; the **Critic** grades it and bounces it back for one or two focused tweaks if needed.

---

## 4. Handling the four risks

### 4.1 Random changes
- **One codepath** for initial + chat. The Strategist always produces a *fresh full* PatchPlan, never a delta merge.
- Chat history + `CURRENT_PLAN` + `PRESERVE_VERBATIM` feed the Strategist so `"revert that"` or `"actually keep the CTA copy"` works.
- Coercion layer (`_coerce_source`, `_coerce_op`, `_coerce_change`) normalizes LLM drift before Pydantic validation — a stray `source: "ad.offer, ad.value_prop"` no longer crashes a turn.
- Temperature capped at 0.4 for structural outputs; Design.md files are stable system prompts.

### 4.2 Broken UI
- We never regenerate the page — Builder is pure Python `BeautifulSoup`, performing seven deterministic ops (`replace_section`, `replace_text`, `set_style`, `set_attr`, `insert_before/after`, `remove`).
- Every selector is a stamped `[data-troopod-id='tN']` — can't target the wrong node.
- Selectors that don't match are logged to `changes_skipped`, never replaced with a guess.
- `<base href>` injected so original assets keep resolving.
- Scripts, manifests, and prefetch `<link>`s stripped from rendered output to prevent the original site's router from hijacking the iframe.
- Full-bleed safety contract in Strategist prompt: hero payload must include `width: 100%; min-width: min(100%, 100vw);` so a misidentified narrow parent can't render a 40px vertical column.
- Verifier does rule checks on every plan; Critic does a *visual* diff against the ad and original screenshots — catches layout breaks the rules miss.

### 4.3 Hallucinations
- **`source` contract on every Change**: exactly one of `ad | page | exa | cro_principle`. Verifier rejects unsourced changes as blocker issues; coercion layer normalizes loose outputs so `ad.offer, ad.cta_text` collapses to `"ad"`.
- Strategist prompt explicitly forbids copying `HERO.headline_text` verbatim — hero text must be *derived* from the ad.
- Chat Strategist (refinement mode) gets a separate `CORE CONTRACT`: preserve existing personalization, only apply the user's specific change; reverting to page copy is "the single biggest failure mode."
- Critic cross-checks message match visually; flags a `hallucinated_claim` when a rendered claim isn't traceable to any source.
- Critic false-positive sanitization: claims like "headline repeated 3×" are validated against the actual DOM (`soup.find_all("h1")` count); if demonstrably false, the issue is dropped.

### 4.4 Inconsistent outputs
- Every agent output is a **Pydantic model**; malformed output fails fast with a named error, not silent propagation.
- Structured JSON via `response_mime_type=application/json` on Gemini; tolerant extractor (`_extract_json`) on OpenAI strips ``` fences and balanced-brace fallback.
- Stamped selectors mean the same `(url, ad_hash)` can be cached — same input, same output.
- `agent_logs` table persists every agent's input + raw LLM output + parsed output + elapsed time → replay and diff any turn.

---

## 5. Assumptions (as the brief invites)

- We interpret *"enhanced as per CRO principles"* as **hero-first personalization** — headline, subheadline, CTA, accent, optional urgency/trust badge. Nav/footer/layout containers are deliberately untouched (risk of broken UI).
- Target viewport: desktop 1440×900. Mobile-specific layouts are out of scope.
- `ad_bytes` cap: 10 MB / PNG·JPG·GIF·WebP (server-side magic-byte check). SVG/HTML uploads are rejected.
- Hallucination guard: no string appears in the personalized page unless it comes from the ad, the original page's copy inventory, or a cited Exa snippet.
- Quality gate: Critic score ≥ 8 ships; 5–7 triggers one refine loop; below 5 triggers a rebuild. Max 2 loops per turn.
- We use the **screenshot** captured during scraping for the "Original" tab, not a reconstructed iframe. This is more faithful (animations, hydration-only content preserved) and matches exactly what the Critic compares against.

---

## 6. Stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 15 + TypeScript + Tailwind 4 → **Vercel** |
| Backend | Python 3.13 + FastAPI + Agno → **Railway** (Docker, Playwright-ready) |
| DB + realtime + storage | **Supabase** (Postgres + Storage + Realtime) |
| Scraping (deep) | Playwright on Railway |
| Scraping (fast) + brand research | Jina Reader (via Agent-Reach) + Exa |
| Models | Gemini 2.5 Pro (vision + critic), OpenAI GPT-4.1 (strategist) |

---

## 7. Repo tour

```
Troopod/
├── api/                          # FastAPI + Agno backend
│   ├── app/
│   │   ├── main.py               # /sessions /chat /render/{id} /render/{id}/original{,.png} /health
│   │   ├── schemas/              # Pydantic I/O contracts
│   │   ├── tools/                # scrape, search, vision, patcher
│   │   └── agents/               # extractor, strategist, builder, verifier, critic, pipeline
│   ├── tests/                    # 26/26 passing
│   ├── Dockerfile                # Playwright python base; non-root; stdout logging
│   └── railway.toml              # build + deploy config
├── web/                          # Next.js 15 frontend (Vercel)
├── supabase/migrations/          # schema + storage + RLS
├── samples/                      # pre-made ad PNGs + README for quick testing
└── docs/
    ├── design/                   # One Design.md per agent (system prompts)
    └── WRITEUP.md                # this file
```

---

## 8. Engineering notes that might interest the reviewer

- **Why unified pipeline.** We originally had a separate `Refiner` agent for chat turns. It produced `plan_deltas` that merged into the existing plan. That architecture caused two classes of bugs: (a) stacked changes on the same selector fighting each other, and (b) the Critic only ran on initial passes, so refinement quality silently drifted lower than initial quality. Unifying — one Strategist path, always, producing fresh full plans — eliminated both. Cost: ~30-60s per chat turn (full critic loop) vs ~10s before. Acceptable for a demo; worth it for consistency.
- **Why the Critic can "hallucinate" positively.** We saw the Critic flag "headline repeated 3×" when the DOM had exactly one `<h1>`. It was seeing Linear's nested-span animation layers as three headlines. Fix: a `_sanitize_critique` pass that checks each claim against the DOM and drops demonstrably false ones before they can trigger a wasteful refine loop.
- **Why user intent beats Critic taste.** User asks `"make hero bg red"` → Critic complains "red isn't in the ad palette". We added a user-intent override: if the instruction mentions a specific color/size, the Critic can no longer veto that change on aesthetic grounds. User intent is law.
- **Why `data-troopod-id` stamping.** CSS selectors on a deeply nested SSR DOM (Next.js, React, shadow roots) are *floating* — `div > div:nth-of-type(5) > h1` matches the first match anywhere in the tree, usually not the hero. Stamping with `data-troopod-id="tN"` at extraction time gives us selector-level determinism: every selector resolves to exactly one element.
- **Why design tokens.** Without grounded fonts/colors/radius/shadow, the Strategist authors hero blocks that look generic. With tokens pulled from `getComputedStyle`, the new hero inherits the site's visual language. Combined with ad palette fallback (when the page's accent is too neutral), we get accents that match the *ad* while the rest of the block looks native to the *page*.

---

## 9. Deployment

### Live demo
- **FE** (Vercel): `<FE_URL>`
- **API** (Railway, Dockerfile): `<API_URL>`
- **DB** (Supabase): `<SUPABASE_URL>`

### One-command reproducibility
```bash
# Backend
cd api && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp ../.env.example .env                       # fill keys
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd web && npm install && cp ../.env.example .env.local
npm run dev
```

### Supabase setup (one-time)
```bash
# In the Supabase SQL editor, run:
supabase/migrations/0001_init.sql
supabase/migrations/0002_page_profile.sql

# Then create these private buckets in Storage:
#   ad-uploads, screenshots, patched-html
```

---

## 10. What's not in this submission

- Mobile-specific layouts.
- Auth / multi-tenancy (demo is open; RLS policies exist but are permissive).
- Analytics / A-B testing of the generated hero variants.
- SSRF guard on the scraper (see `DEPLOY.md` for the note).

These are explicit scope cuts, not oversights. Happy to discuss.
