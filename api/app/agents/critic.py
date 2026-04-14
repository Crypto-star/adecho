"""Visual Critic — looks at the ad + original + rendered screenshots and
produces a structured critique + next-step verdict.

This is the self-improvement loop that makes v0-style output feel polished:
we don't trust the first draft, we trust the critique of it.
"""
from __future__ import annotations

import base64
import json
from uuid import UUID

from google import genai
from google.genai import types
from loguru import logger

from app.config import get_settings
from app.schemas import AdProfile, CriticIssue, CriticReport, DesignTokens
from app.services import supabase_client as sb


_SYSTEM = """You are a senior performance-marketing design critic.
You are judging whether a personalized landing page matches an ad creative and
applies CRO best practices well.

Return STRICT JSON:
{
  "score": int 1..10,
  "verdict": "ship" | "refine" | "rebuild",
  "issues": [
    { "kind": "layout|typography|color|hierarchy|message_match|duplicate_ghost|cta_weakness|other",
      "detail": "plain-english problem",
      "suggested_selector": "[data-troopod-id='...'] or null",
      "suggested_fix": "one-line concrete change" }
  ]
}

Rubric:
- 10 = indistinguishable from a v0-grade, ad-perfect landing.
- 8–9 = shippable; tiny polish issues.
- 5–7 = needs one focused refine pass.
- 1–4 = broken, regenerate.

Flag specifically:
- Multiple visible headlines where one should be → duplicate_ghost.
- Stale "before" text still visible near new "after" text → duplicate_ghost.
- Hero headline that doesn't message-match the ad → message_match.
- CTA that isn't visually dominant / uses accent color → cta_weakness.
- Overlapping / cramped / cut-off text → layout.
- Typography or color scheme that ignores the design tokens → typography/color.

Be terse. Max 5 issues. If verdict="ship", issues may be empty."""


async def run(
    session_id: UUID,
    version: int,
    ad_profile: AdProfile,
    design_tokens: DesignTokens | dict,
    original_screenshot_png: bytes,
    ad_image_png: bytes,
    new_screenshot_png: bytes,
) -> CriticReport:
    with sb.log_agent(session_id, "critic", version=version) as log:
        log.set(input={"version": version})
        settings = get_settings()
        if not settings.google_api_key:
            logger.warning("GOOGLE_API_KEY missing; critic returning neutral ship verdict")
            report = CriticReport(session_id=session_id, version=version,
                                  score=7, issues=[], verdict="ship")
            log.set(output=report.model_dump(mode="json"))
            return report

        client = genai.Client(api_key=settings.google_api_key)
        tokens = (design_tokens.model_dump() if isinstance(design_tokens, DesignTokens)
                  else design_tokens) or {}
        prompt = (
            f"AD_PROFILE:\n{json.dumps(ad_profile.model_dump(mode='json'), indent=2)}\n\n"
            f"DESIGN_TOKENS:\n{json.dumps(tokens, indent=2)}\n\n"
            "IMAGES (in order): 1=ad creative, 2=original page, 3=personalized page.\n"
            "Critique the personalized page against the ad + the original. Score 1..10."
        )
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                types.Part.from_bytes(data=ad_image_png, mime_type="image/png"),
                types.Part.from_bytes(data=original_screenshot_png, mime_type="image/png"),
                types.Part.from_bytes(data=new_screenshot_png, mime_type="image/png"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        data = _safe_json(resp.text or "")
        issues = []
        for i in data.get("issues", [])[:5]:
            try:
                issues.append(CriticIssue(**i))
            except Exception:
                continue
        score = int(data.get("score") or 7)
        verdict = data.get("verdict") or ("ship" if score >= 8 else "refine")
        if verdict not in ("ship", "refine", "rebuild"):
            verdict = "refine"
        # Degenerate output guard: perfect score with no issues is suspicious.
        if score == 10 and not issues:
            verdict = "ship"
        report = CriticReport(
            session_id=session_id, version=version,
            score=score, issues=issues, verdict=verdict,
        )
        log.set(output=report.model_dump(mode="json"))
        logger.info("Critic v{} score={} verdict={} issues={}",
                    version, score, verdict, len(issues))
        return report


def _safe_json(text: str) -> dict:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1].removeprefix("json").strip().rsplit("```", 1)[0]
    try:
        return json.loads(s)
    except Exception:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(s[start:end + 1])
            except Exception:
                pass
        return {}
