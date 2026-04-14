# Agent: Builder

## Role
Apply the `PatchPlan` to the scraped HTML deterministically. This agent is mostly code, not LLM — the LLM only steps in when a `new_module` HTML snippet must be generated.

## Model (only for module synthesis)
GPT-4.1 or Claude Sonnet. Temperature 0.2. Constrained: must emit HTML that uses existing Tailwind/utility classes from the page.

## Tools
- `apply_patch(html, plan) -> str` — pure BeautifulSoup logic. No LLM.
- `synthesize_module(spec, page_profile)` — LLM call for new_modules only.

## Input
- Scraped `html` (str)
- `PatchPlan`
- `PageProfile` (for class-name palette)

## Output
```python
class RenderArtifact(BaseModel):
    session_id: UUID
    version: int
    patched_html: str
    changes_applied: list[str]        # selectors that matched
    changes_skipped: list[str]        # selectors that did not match (fallback triggered)
```

## Guardrails
- `<base href="{original_url}">` is injected into `<head>` so original assets continue loading.
- If a selector does not match → log to `changes_skipped` and move on. **Never** fabricate a substitute selector.
- Strip `<script>` tags that reference third-party analytics to avoid flooding the render iframe with console noise.
- Sanitize any `payload` HTML against a safelist before insertion.
- The output HTML is served via `/render/{session_id}` and must be standalone loadable.
