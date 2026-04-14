# Agent: Verifier

## Role
Independently check the rendered result. Can veto a render and send it back to the Builder (max 2 retries per session version).

## Model
Gemini 2.5 Pro (vision). Temperature 0.1.

## Tools
- `screenshot_render(session_id)` → Playwright → PNG of the patched page at 1440×900.
- `fact_check(claim)` → Exa search → return top 3 snippets + whether any substantiates the claim.

## Input
- `RenderArtifact`
- `AdProfile`, `PageProfile` (for grounding)
- `PatchPlan` (to check every claim source)

## Output
```python
class Issue(BaseModel):
    severity: Literal["blocker","warn"]
    kind: Literal["layout_broken","message_mismatch","hallucinated_claim","missing_cta","contrast_fail","other"]
    detail: str
    selector: str | None

class VerifierReport(BaseModel):
    session_id: UUID
    version: int
    passed: bool
    issues: list[Issue]
    screenshot_path: str
```

## Checks
1. **Layout integrity** — compare screenshot to original screenshot; flag obviously collapsed sections, overflow, missing hero.
2. **Message match** — hero copy should restate the ad's offer.
3. **Hallucination check** — for every `Change` with `source != "ad" | "page"`, require a cited Exa snippet or fail with `hallucinated_claim`.
4. **CTA presence** — primary CTA must exist and be above the fold.
5. **Contrast** — accent color text on its background ≥ WCAG AA.

## Guardrails
- A `blocker` issue ⇒ `passed=false` ⇒ Builder retries with Verifier's issues appended to its context.
- After 2 failed retries, surface the last render + the report to the user rather than looping forever.
