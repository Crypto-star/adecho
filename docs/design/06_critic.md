# Agent: Visual Critic

## Role
Look at the rendered personalized page side-by-side with the original ad creative, score it, and produce concrete fix suggestions. This is the closest analogue to v0/Lovable's self-improvement loop: we don't trust the first draft — we trust the *critique* of it.

## Model
Gemini 2.5 Pro (vision). Temperature 0.2.

## Tools
- `screenshot_render(html, base_url)` → Playwright `set_content` → 1440×900 PNG.
- Passes **three images** to the model in one call:
  1. The ad creative.
  2. The original (pre-patch) page screenshot.
  3. The newly rendered (patched) page screenshot.

## Input
```python
class CriticInput(BaseModel):
    session_id: UUID
    version: int
    ad_profile: AdProfile
    design_tokens: dict             # from Extractor
    original_screenshot_path: str   # supabase storage path
    new_screenshot_png: bytes       # freshly rendered patched page
```

## Output
```python
class CriticIssue(BaseModel):
    kind: Literal["layout", "typography", "color", "hierarchy",
                  "message_match", "duplicate_ghost", "cta_weakness", "other"]
    detail: str                     # plain-english problem
    suggested_selector: str | None  # stamped selector the Builder should touch
    suggested_fix: str | None       # concrete hint ("make bg the accent color", etc.)

class CriticReport(BaseModel):
    score: int                      # 1..10 — how close the result is to a v0-grade landing
    issues: list[CriticIssue]
    verdict: Literal["ship", "refine", "rebuild"]
```

## Heuristics baked into the prompt
- **Message match** — hero text must restate the ad's offer within 1 scan.
- **Hierarchy** — single clear headline → subheadline → one primary CTA. No competing CTAs above the fold.
- **Ghost siblings** — if multiple headlines/CTAs are visible where one should be (Linear animation layers), flag `duplicate_ghost`.
- **Typography** — respect the design_tokens (heading font family, size relationships).
- **Color hierarchy** — accent color should be used *sparingly* on CTA(s) only; never floods backgrounds.
- **Overflow / crop** — visible text cut-off, overlapping elements → `layout`.

## Feedback loop
- `score ≥ 8` or `verdict="ship"` → pipeline exits as passed.
- `verdict="refine"` → feed `issues + suggested_fix` into **Strategist** (not a full rebuild); produces v+1 plan focused on the critic's issues.
- `verdict="rebuild"` → Strategist starts from scratch with `prior_issues` including critic's report.
- Max 2 critic loops per session.

## Guardrails
- The critic only critiques *visible* pixels. It cannot invent new claims.
- If the critic's `suggested_selector` is not in the page_profile, drop that suggestion (do not let critic hallucinate selectors).
- If score is suspiciously high (10) with no issues, treat as degenerate output and keep the current version without further loops.
