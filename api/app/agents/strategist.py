"""Strategist — produces a PatchPlan from ExtractorOutput using Agno + Claude/GPT."""
from __future__ import annotations

import json
from uuid import UUID

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from loguru import logger

from app.agents.prompts import STRATEGIST
from app.config import get_settings
from app.schemas import Change, ExtractorOutput, PatchPlan
from app.services import supabase_client as sb


_SELECTOR_GUIDANCE = """
## CORE CONTRACT — READ THIS FIRST

You have TWO possible jobs depending on whether CURRENT_PLAN is present:

1. **Initial personalization** (no CURRENT_PLAN):
   Produce a hero block that MESSAGE-MATCHES the ad. The new headline and
   subheadline MUST be derived from AD_PROFILE.offer / AD_PROFILE.value_prop /
   AD_PROFILE.claims — NEVER copy HERO.headline_text verbatim. That original
   text is there for your reference only, not for re-use. Re-using page copy
   defeats the whole point of personalization.

2. **Refinement** (CURRENT_PLAN present + a USER_INSTRUCTION):
   PRESERVE the current personalization exactly. Only apply the specific
   change the user asked for. If they asked for a color change, only change
   colors. If they asked for copy change, only change the specific copy. DO
   NOT regenerate the hero from scratch. DO NOT revert to HERO.headline_text.
   Carry the existing replace_section's headline/subheadline/CTA text
   forward verbatim except for the slice the user wanted changed.

Violating rule 1 or 2 is the single biggest failure mode. It is worse than
any other kind of error — the user sees their personalization vanish.

## V2 — BLOCK SURGERY, NOT TEXT NIBBLING

Prefer ONE `replace_section` on the hero container over many small
`replace_text` changes. Text-level changes leave stale siblings visible
(Linear-style ghost headlines).

## SELECTOR RULES (hard)
- Use ONLY selectors present verbatim in EXTRACTOR_OUTPUT.
- `replace_section` target MUST be `page.hero_container_selector`.
- `replace_text` / `set_style` targets must be from `page.hero.*` or a key of
  `page.copy_inventory`.
- Each (selector, op) pair appears AT MOST ONCE in `changes`.
- Do not invent selectors.

## AUTHORING CONTRACT for replace_section payload
- Self-contained hero block: headline + subheadline + primary CTA
  (+ optional urgency/trust badge).
- Inline styles ONLY (use DESIGN_TOKENS for colors, fonts, radius, spacing).
- Primary CTA: solid `background:{tokens.colors.brand_accent}`, white text,
  padding ~14px 22px, border-radius `{tokens.radius}`, no underline.
- Headline: `font-family:{tokens.fonts.heading}`, bold, 40–56px.
- Subcopy: `font-family:{tokens.fonts.body}`, 18px, muted color.
- MAX 120 words total inside the block.
- No <script>, <iframe>, <meta>, no on* handlers.

## FULL-BLEED SAFETY — CRITICAL
Some pages embed the hero container inside a narrow parent (modal wrappers,
sidebars, flex children). To avoid rendering as a 40px-wide vertical column,
your outer `<div>` payload MUST include these properties:
  width: 100%;
  box-sizing: border-box;
  min-width: min(100%, 100vw);
  padding: clamp(48px, 6vw, 96px) clamp(20px, 4vw, 48px);
Do NOT set `max-width: none` on the outer wrapper. Use a sensible
`max-width: {tokens.container_max_width}` on an INNER centering div instead.
Never output width < 400px or max-width: Xpx with X < 600.

## ANTI-HALLUCINATION
Every text string in the payload must come from AD_PROFILE fields, a PAGE_COPY
entry, or a cited Exa snippet. Source field on the change must reflect that.

## BUDGET
Total `changes` ≤ 6. A typical v2 plan is:
  1 × replace_section (hero container)
  0–2 × set_style (accent polish)
  0–1 × new_modules entry (urgency bar at body_start)

## OUTPUT — strict JSON
{accent_color: "#rrggbb"|null,
 changes:[{selector, op, payload, rationale, source}],
 new_modules:[{position:"body_start"|"body_end", html}],
 notes: str}

## source FIELD — STRICT
`source` is EXACTLY ONE of these four string literals — never a comma list,
never a field path, never a description:
  "ad"              the ad creative's own text/visuals
  "page"            text/visuals present on the original page
  "exa"             an Exa-cited web snippet in brand_context
  "cro_principle"   pure CRO best-practice (no external claim)

Example VALID:  "source": "ad"
Example INVALID: "source": "ad.offer, ad.value_prop"   ← do not do this
"""


def _make_agent() -> Agent:
    return Agent(
        model=OpenAIChat(id="gpt-4.1-mini", api_key=get_settings().openai_api_key),
        system_message=STRATEGIST + _SELECTOR_GUIDANCE,
        markdown=False,
    )


async def run(
    session_id: UUID,
    version: int,
    extract: ExtractorOutput,
    *,
    user_instruction: str = "Personalize this page for the ad creative. Apply CRO best practices.",
    current_plan: PatchPlan | None = None,
    chat_history: list[dict] | None = None,
    prior_issues: list | None = None,
) -> PatchPlan:
    """Produce a PatchPlan for this turn.

    A *turn* is either the initial pass (no current_plan, default instruction)
    or a chat refinement (current_plan present, instruction is the user's
    latest message). Either way the output is a fresh, full plan — not a delta.

    chat_history: recent turns (list of {role, content}) so the model sees the
    arc, not only the latest message — so 'revert that' works.
    """
    with sb.log_agent(session_id, "strategist", version=version) as log:
        log.set(input={
            "user_instruction": user_instruction,
            "has_current_plan": current_plan is not None,
            "chat_history_len": len(chat_history or []),
            "prior_issues_len": len(prior_issues or []),
        })

        if not get_settings().openai_api_key:
            logger.warning("OPENAI_API_KEY missing; returning trivial no-op plan")
            plan = PatchPlan(session_id=session_id, version=version,
                             notes="No model key configured.")
            sb.save_patch_plan(session_id, version, plan.model_dump(mode="json"))
            log.set(output=plan.model_dump(mode="json"))
            return plan

        agent = _make_agent()

        # Trim copy_inventory to keep the prompt small but keep hero + first 60 entries.
        trimmed = extract.model_dump(mode="json")
        inv = trimmed["page"].get("copy_inventory") or {}
        trimmed["page"]["copy_inventory"] = dict(list(inv.items())[:60])

        hero = extract.page.hero or {}
        tokens = extract.page.design_tokens.model_dump()
        container = extract.page.hero_container_selector or hero.get("headline_selector")
        issues_block = ""
        if prior_issues:
            # Render issues as a do-not list so the retry converges.
            from app.schemas import Issue
            rendered = []
            for i in prior_issues:
                d = i.model_dump() if isinstance(i, Issue) else dict(i)
                rendered.append(f"  - [{d.get('severity')}] {d.get('kind')}: "
                                f"{d.get('detail')}  (selector={d.get('selector')})")
            issues_block = (
                "\nPRIOR_VERIFIER_ISSUES (the previous plan failed for these reasons — "
                "do NOT repeat them):\n" + "\n".join(rendered) + "\n"
            )
        # Chat history block — recent turns so model sees the arc.
        history_block = ""
        if chat_history:
            last = chat_history[-8:]  # cap to last 8 turns
            formatted = "\n".join(f"  {m['role']}: {m['content'][:220]}" for m in last)
            history_block = f"\nCHAT_HISTORY (most recent last):\n{formatted}\n"

        # Current plan block — so refinements build on what we already shipped.
        plan_block = ""
        preserved_copy = _extract_current_hero_copy(current_plan)
        if current_plan is not None:
            plan_block = (
                "\nCURRENT_PLAN (the personalization you shipped last turn). "
                "YOU MUST CARRY ITS HEADLINE/SUBHEADLINE/CTA TEXT FORWARD "
                "EXACTLY. Only change what USER_INSTRUCTION asks for:\n"
                + json.dumps(current_plan.model_dump(mode="json"), indent=2) + "\n"
            )
            if preserved_copy:
                plan_block += (
                    "\nPRESERVE_VERBATIM (reuse these strings in your new "
                    "replace_section payload unless the user specifically asks "
                    "to change them):\n"
                    + json.dumps(preserved_copy, indent=2) + "\n"
                )

        prompt = (
            f"USER_INSTRUCTION (the thing to accomplish this turn):\n"
            f"  {user_instruction}\n\n"
            f"HERO_CONTAINER (use for replace_section): {container!r}\n"
            f"HERO.headline_selector = {hero.get('headline_selector')!r}\n"
            f"HERO.cta_selector      = {hero.get('cta_selector')!r}\n"
            f"HERO.headline_text     = {hero.get('headline_text')!r}\n"
            f"HERO.cta_text          = {hero.get('cta_text')!r}\n\n"
            f"DESIGN_TOKENS:\n{json.dumps(tokens, indent=2)}\n"
            + history_block
            + plan_block
            + issues_block +
            "\nEXTRACTOR_OUTPUT:\n"
            + json.dumps(trimmed, indent=2)
            + "\n\nReturn a FRESH full PatchPlan JSON now. "
            "Always prefer ONE replace_section over many small text swaps."
        )
        resp = await agent.arun(prompt)
        raw = (resp.content or "").strip()
        plan_json = _extract_json(raw)
        plan = PatchPlan(
            session_id=session_id,
            version=version,
            accent_color=plan_json.get("accent_color"),
            changes=[
                Change(**_coerce_change(c))
                for c in plan_json.get("changes", [])
                if _valid_change(c)
            ],
            new_modules=plan_json.get("new_modules", []),
            notes=plan_json.get("notes", ""),
        )
        sb.save_patch_plan(session_id, version, plan.model_dump(mode="json"))
        log.set(output=plan.model_dump(mode="json"))
        return plan


def _extract_current_hero_copy(plan: "PatchPlan | None") -> dict | None:
    """Pull headline / subheadline / CTA text out of the current plan's
    replace_section payload so the next turn can preserve them verbatim."""
    if plan is None:
        return None
    for ch in plan.changes:
        if ch.op != "replace_section" or not isinstance(ch.payload, str):
            continue
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(ch.payload, "lxml")
            h1 = soup.find(["h1", "h2"])
            subcopy = soup.find("p")
            cta = soup.find(["a", "button"])
            result = {
                "headline": h1.get_text(" ", strip=True) if h1 else None,
                "subheadline": subcopy.get_text(" ", strip=True) if subcopy else None,
                "cta_text": cta.get_text(" ", strip=True) if cta else None,
            }
            if any(result.values()):
                return result
        except Exception:
            return None
    return None


_VALID_SOURCES = ("ad", "page", "exa", "cro_principle")
_VALID_OPS = ("replace_text", "replace_html", "replace_section",
              "set_attr", "set_style", "insert_after", "insert_before", "remove")


def _coerce_source(raw) -> str:
    """LLMs sometimes emit source as a comma list or a field path; normalize.

    Precedence ad > page > exa > cro_principle when multiple are mentioned
    (matches the intent: claim-from-ad is the strongest provenance)."""
    s = (str(raw) if raw is not None else "").lower()
    for key in _VALID_SOURCES:
        if key in s:
            return key
    return "cro_principle"


def _coerce_op(raw) -> str:
    s = (str(raw) if raw is not None else "").lower().strip()
    return s if s in _VALID_OPS else "replace_text"


def _valid_change(c: dict) -> bool:
    """Drop obviously malformed changes rather than failing the whole plan."""
    return bool(isinstance(c, dict) and c.get("selector") and c.get("payload") is not None)


def _coerce_change(c: dict) -> dict:
    return {
        "selector": c["selector"],
        "op": _coerce_op(c.get("op")),
        "payload": c["payload"],
        "rationale": c.get("rationale") or "",
        "source": _coerce_source(c.get("source")),
    }


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction — handles ```json fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Try first {...} balanced block
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1:
            return json.loads(s[start:end + 1])
        raise
