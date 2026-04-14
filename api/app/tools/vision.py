"""Ad image understanding via Gemini vision + HTML screenshot helper."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types
from loguru import logger
from playwright.async_api import async_playwright

from app.config import get_settings


async def render_screenshot(html: str, viewport_w: int = 1440, viewport_h: int = 900) -> bytes:
    """Render an HTML string and return a PNG screenshot.

    Uses `page.set_content()` so large HTML (Linear, Notion) does not hit the
    ~2MB cap on `data:` URLs. The injected `<base href>` inside the HTML keeps
    relative assets resolving correctly.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(viewport={"width": viewport_w, "height": viewport_h})
        page = await ctx.new_page()
        try:
            await page.set_content(html, wait_until="domcontentloaded", timeout=25000)
            try:
                await page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
            png = await page.screenshot(full_page=False, type="png")
        finally:
            await browser.close()
    return png

_SYSTEM = """You are an expert performance marketer.
Given an ad creative image, return STRICT JSON with keys:
  offer (str), value_prop (str),
  tone (one of: bold, friendly, professional, playful, urgent, premium),
  audience (str),
  visual_style (object: {palette: [hex strings], typography: str, mood: str}),
  claims (array of strings — ONLY claims literally legible in the image),
  cta_text (str or null).
Return only JSON. No commentary."""


async def analyze_ad(image_bytes: bytes, mime: str = "image/png") -> dict[str, Any]:
    s = get_settings()
    if not s.google_api_key:
        logger.warning("GOOGLE_API_KEY not set; returning stub ad profile")
        return _stub()
    client = genai.Client(api_key=s.google_api_key)
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            "Analyze this ad creative per the schema in the system instruction.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    try:
        return json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        logger.warning("Gemini returned non-JSON; falling back to stub")
        return _stub()


def _stub() -> dict[str, Any]:
    return {
        "offer": "Unknown offer",
        "value_prop": "Unknown value proposition",
        "tone": "friendly",
        "audience": "general",
        "visual_style": {"palette": [], "typography": "sans-serif", "mood": "neutral"},
        "claims": [],
        "cta_text": None,
    }
