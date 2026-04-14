# Agent: Extractor

## Role
Produce a structured understanding of **(a)** the uploaded ad creative and **(b)** the user's landing page, plus light brand context. This is the sole source of truth for everything downstream.

## Model
Gemini 2.5 Pro (vision-capable). Temperature 0.2.

## Tools
- `read_landing_page_fast(url)` → Jina Reader via `agent_reach.channels.web.WebChannel` → clean markdown.
- `scrape_landing_page_deep(url)` → Playwright headless → `{html, dom_tree, css_vars, palette, screenshot_png}`.
- `analyze_ad(image_bytes)` → Gemini vision call.
- `search_brand(query)` → Exa (via agent-reach or HTTP fallback) → up to 5 snippets.

## Input
```python
class ExtractorInput(BaseModel):
    session_id: UUID
    ad_image_path: str        # supabase storage path
    landing_url: HttpUrl
```

## Output
```python
class AdProfile(BaseModel):
    offer: str                # "50% off first order"
    value_prop: str
    tone: Literal["bold","friendly","professional","playful","urgent","premium"]
    audience: str
    visual_style: dict        # {palette: [hex], typography: str, mood: str}
    claims: list[str]         # explicit claims visible in ad
    cta_text: str | None

class PageProfile(BaseModel):
    hero: dict                # {headline_selector, subheadline_selector, cta_selector, text}
    sections: list[dict]      # [{selector, role, text_excerpt}]
    brand_palette: list[str]  # hex
    copy_inventory: dict[str, str]  # selector -> current text
    screenshot_path: str

class BrandContext(BaseModel):
    snippets: list[dict]      # [{source_url, text, fetched_at}]

class ExtractorOutput(BaseModel):
    ad: AdProfile
    page: PageProfile
    brand: BrandContext
```

## Guardrails
- If the page requires JS and Jina returns empty markdown → fall back to Playwright's `page.content()`.
- If the page blocks headless browsers → return `page.status = "blocked"` and let the pipeline surface a clear error instead of faking data.
- Never invent claims. If a claim isn't *legible in the ad image*, do not include it in `ad.claims`.
- Cap `copy_inventory` at 200 entries to bound downstream token use.
