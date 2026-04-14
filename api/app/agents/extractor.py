"""Extractor pipeline — orchestrates vision + scrape + brand research."""
from __future__ import annotations

import asyncio
from uuid import UUID

from loguru import logger

from app.schemas import AdProfile, BrandContext, BrandSnippet, ExtractorOutput, PageProfile
from app.services import supabase_client as sb
from app.tools.scrape import build_page_profile, read_fast, scrape_deep
from app.tools.search import exa_search
from app.tools.vision import analyze_ad


async def run(
    session_id: UUID, ad_bytes: bytes, ad_mime: str, landing_url: str,
) -> tuple[ExtractorOutput, str]:
    """Returns (extractor_output, stamped_html). The HTML is returned in-memory
    so the Builder can patch it directly without a DB round-trip — which also
    keeps the pipeline working when Supabase isn't configured."""
    with sb.log_agent(session_id, "extractor") as log:
        log.set(input={"landing_url": landing_url, "ad_bytes_len": len(ad_bytes)})

        ad_task = analyze_ad(ad_bytes, mime=ad_mime)
        md_task = read_fast(landing_url)
        deep_task = scrape_deep(landing_url)

        ad_json, markdown, deep = await asyncio.gather(ad_task, md_task, deep_task)

        screenshot_path = sb.upload_bytes(
            "screenshots", f"{session_id}/original.png",
            deep["screenshot_png"], "image/png",
        )
        page = build_page_profile(deep["html"], screenshot_path)
        stamped_html = page.pop("_stamped_html", deep["html"])
        # Merge in computed design tokens from the browser.
        tokens = deep.get("design_tokens") or {}
        # If the page-derived brand_accent is too neutral (black/white/transparent),
        # fall back to the ad's extracted palette — that's the visual language
        # the user actually wants matched. Prevents "black CTA on purple ad" ugly.
        accent = (tokens.get("colors") or {}).get("brand_accent", "") or ""
        if _is_neutral(accent):
            ad_palette = ((ad_json.get("visual_style") or {}).get("palette") or [])
            for c in ad_palette:
                if not _is_neutral(c):
                    tokens.setdefault("colors", {})["brand_accent"] = c
                    break
        page["design_tokens"] = tokens
        sb.save_scrape(
            session_id,
            html=stamped_html, markdown=markdown,
            screenshot_path=screenshot_path, palette=deep["palette"],
        )

        # Brand research: query Exa for brand name implied by title or ad offer.
        query = (deep.get("title") or ad_json.get("offer") or "").strip()
        snippets = await exa_search(query, num_results=3) if query else []
        brand = BrandContext(snippets=[
            BrandSnippet(
                source_url=s.get("url") or "",
                text=s.get("text") or "",
                fetched_at=_now(),
            )
            for s in snippets if s.get("url")
        ])

        out = ExtractorOutput(
            ad=AdProfile(**ad_json),
            page=PageProfile(**page),
            brand=brand,
        )
        sb.save_ad_extract(
            session_id, ad_json, brand.model_dump(),
            page_profile=out.page.model_dump(mode="json"),
        )
        log.set(output=out.model_dump(mode="json"))
        logger.info("Extractor done for session {}", session_id)
        return out, stamped_html


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _is_neutral(color: str) -> bool:
    """True if the color is black/near-black, white/near-white, grey, or empty.
    Such colors make terrible CTA accents — prefer the ad's palette instead."""
    c = (color or "").strip().lower()
    if not c:
        return True
    # Drop hashes, normalize 3-digit hex
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return True  # couldn't parse → treat as neutral so fallback kicks in
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return True
    # Near-black, near-white, or low-chroma grey.
    m, M = min(r, g, b), max(r, g, b)
    if M - m < 20:  # nearly monochrome
        return True
    return False
