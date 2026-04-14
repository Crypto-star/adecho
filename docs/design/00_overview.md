# Agent Pipeline Overview — Unified Loop

## The contract

Troopod never regenerates landing pages. Every agent in this pipeline operates
on the user's **actual scraped HTML**. Output is always a **patch**, never a
replacement.

## One loop, always

Both the initial "personalize for this ad" pass and every chat refinement run
through the SAME pipeline. There is no separate Refiner agent — chat turns
just feed the Strategist a different `user_instruction` plus the current plan
and chat history as context.

```
┌──────────────────────────────────────────────────────────────┐
│   for every turn (initial OR chat refinement):               │
│                                                              │
│   user_instruction ──►  Strategist                           │
│                         │  (fresh full PatchPlan, not delta) │
│                         ▼                                    │
│                      Builder                                 │
│                         │  (DOM surgery via BeautifulSoup)   │
│                         ▼                                    │
│                     Verifier                                 │
│                         │  (rule checks — passes?)           │
│                         ▼                                    │
│                       Critic                                 │
│                         │  (vision — ad vs. result)          │
│                         ▼                                    │
│                    ship | refine ──┐                         │
│                                    │                         │
│             (≤2 refine loops) ◄────┘                         │
└──────────────────────────────────────────────────────────────┘
```

Initial turn's extractor is run once at session creation; subsequent chat
turns reuse the stored ExtractorOutput.

## Shared conventions

- Every agent output is a Pydantic model, validated before the next agent runs.
- Temperatures: 0.2–0.4 for structural outputs, 0.2 for visual critique.
- Every stage logs input/output/elapsed_ms to `agent_logs` in Supabase.
- Session state lives in Postgres; files in Supabase Storage.
- Design.md is injected as the system prompt for each agent (stable, versioned).

## Anti-hallucination contract

Only these are valid sources for claims in the personalized page:
1. Text/visuals present in the uploaded ad creative.
2. Text/visuals present in the scraped original landing page.
3. Exa search results explicitly cited in the agent's output.

Anything else is a hallucination and must be rejected by the Verifier.

## How the 4 doc questions are handled (unified loop edition)

- **Random changes** — Strategist sees `current_plan` and evolves it; user's
  history informs the arc (`"revert that"` works). One codepath, no drift.
- **Broken UI** — DOM surgery only. Verifier rule check + Critic pixel check
  both run on EVERY turn. No chat refinement skips the quality gate.
- **Hallucinations** — `source` field on every Change (`ad|page|exa|
  cro_principle`), Verifier rejects unsourced, Critic cross-checks visually.
- **Inconsistent outputs** — Pydantic schemas + coercion layer + one codepath
  + Design.md as stable system prompts. Low temperature on structural output.
