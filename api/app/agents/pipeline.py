"""Unified pipeline: one loop drives both the initial pass and every chat turn.

There is no separate Refiner agent. The Strategist takes a `user_instruction`
(default: "Personalize this page for the ad creative") and produces a fresh
full PatchPlan each turn. Builder → Verifier → Critic runs every time.
"""
from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.agents import builder, critic as critic_agent, extractor, strategist, verifier
from app.schemas import ExtractorOutput, PatchPlan, RenderArtifact, VerifierReport
from app.services import supabase_client as sb
from app.tools.vision import render_screenshot


class TurnResult:
    def __init__(
        self,
        *,
        plan: PatchPlan,
        render: RenderArtifact,
        verifier_report: VerifierReport,
        critic_score: int,
        critic_verdict: str,
        critic_issues: list,
    ):
        self.plan = plan
        self.render = render
        self.verifier_report = verifier_report
        self.critic_score = critic_score
        self.critic_verdict = critic_verdict
        self.critic_issues = critic_issues


# ── Public entry points ──────────────────────────────────────────────────

async def run_initial(
    session_id: UUID, ad_bytes: bytes, ad_mime: str,
    landing_url: str, max_retries: int = 2,
) -> TurnResult:
    """First turn: scrape + extract, then drive the loop with the default
    'personalize for this ad' instruction."""
    sb.update_session(session_id, status="extracting")
    extract, html = await extractor.run(session_id, ad_bytes, ad_mime, landing_url)
    return await _drive(
        session_id=session_id,
        extract=extract,
        html=html,
        landing_url=landing_url,
        user_instruction=(
            "Personalize this page for the uploaded ad creative. "
            "Apply CRO best practices: clear hero, one primary CTA, "
            "message-match the ad's offer and tone."
        ),
        current_plan=None,
        chat_history=None,
        ad_bytes=ad_bytes,
        starting_version=1,
        max_retries=max_retries,
    )


async def run_turn(
    session_id: UUID, user_instruction: str, max_retries: int = 2,
) -> TurnResult:
    """Subsequent chat turn: reuse the stored extract + scrape, evolve the
    plan based on user_instruction + chat history."""
    extract, html, landing_url, current_plan, history, ad_bytes = await _load_context(session_id)
    next_version = (current_plan.version if current_plan else 0) + 1
    return await _drive(
        session_id=session_id,
        extract=extract,
        html=html,
        landing_url=landing_url,
        user_instruction=user_instruction,
        current_plan=current_plan,
        chat_history=history,
        ad_bytes=ad_bytes,
        starting_version=next_version,
        max_retries=max_retries,
    )


# ── Private: the shared loop ─────────────────────────────────────────────

async def _drive(
    *,
    session_id: UUID,
    extract: ExtractorOutput,
    html: str,
    landing_url: str,
    user_instruction: str,
    current_plan: PatchPlan | None,
    chat_history: list[dict] | None,
    ad_bytes: bytes,
    starting_version: int,
    max_retries: int,
) -> TurnResult:
    version = starting_version
    sb.update_session(session_id, status="strategizing", current_version=version)
    plan = await strategist.run(
        session_id, version, extract,
        user_instruction=user_instruction,
        current_plan=current_plan,
        chat_history=chat_history,
    )

    sb.update_session(session_id, status="building")
    render = await builder.run(session_id, html, plan, base_url=landing_url)

    sb.update_session(session_id, status="verifying")
    report = await verifier.run(session_id, render, plan, extract, base_url=landing_url)

    # Rule-based verifier retry loop (hallucinations, contract violations).
    retries = 0
    while not report.passed and retries < max_retries:
        retries += 1
        version += 1
        logger.info("Verifier rejected v{}; retry {}/{}", version - 1, retries, max_retries)
        sb.update_session(session_id, current_version=version)
        plan = await strategist.run(
            session_id, version, extract,
            user_instruction=user_instruction,
            current_plan=plan,
            chat_history=chat_history,
            prior_issues=report.issues,
        )
        render = await builder.run(session_id, html, plan, base_url=landing_url)
        report = await verifier.run(session_id, render, plan, extract, base_url=landing_url)

    # Visual Critic loop (only if verifier passed).
    critic_loops = 0
    critic_score = 0
    critic_verdict = "skip"
    critic_issues: list = []
    if report.passed:
        original_shot = await _load_original_screenshot(session_id)
        new_shot = await render_screenshot(render.patched_html)
        critique = await critic_agent.run(
            session_id, version, extract.ad, extract.page.design_tokens,
            original_shot, ad_bytes, new_shot,
        )
        critique = _sanitize_critique(critique, render.patched_html, user_instruction)
        critic_score, critic_verdict, critic_issues = (
            critique.score, critique.verdict, critique.issues
        )
        while critique.verdict != "ship" and critic_loops < max_retries:
            critic_loops += 1
            version += 1
            logger.info("Critic score={} verdict={}; refine {}/{}",
                        critique.score, critique.verdict, critic_loops, max_retries)
            sb.update_session(session_id, current_version=version)
            prior = [
                {"severity": "blocker" if critique.verdict == "rebuild" else "warn",
                 "kind": _map_kind(i.kind),
                 "detail": f"{i.detail} — fix: {i.suggested_fix}",
                 "selector": i.suggested_selector}
                for i in critique.issues
            ]
            plan = await strategist.run(
                session_id, version, extract,
                user_instruction=user_instruction,
                current_plan=plan,
                chat_history=chat_history,
                prior_issues=prior,
            )
            render = await builder.run(session_id, html, plan, base_url=landing_url)
            report = await verifier.run(session_id, render, plan, extract, base_url=landing_url)
            if not report.passed:
                break
            new_shot = await render_screenshot(render.patched_html)
            critique = await critic_agent.run(
                session_id, version, extract.ad, extract.page.design_tokens,
                original_shot, ad_bytes, new_shot,
            )
            critique = _sanitize_critique(critique, render.patched_html, user_instruction)
            critic_score, critic_verdict, critic_issues = (
                critique.score, critique.verdict, critique.issues
            )

    sb.update_session(
        session_id,
        status="ready" if report.passed else "failed",
        current_version=version,
    )
    return TurnResult(
        plan=plan,
        render=render,
        verifier_report=report,
        critic_score=critic_score,
        critic_verdict=critic_verdict,
        critic_issues=critic_issues,
    )


# ── Helpers ──────────────────────────────────────────────────────────────

def _sanitize_critique(critique, patched_html: str, user_instruction: str = ""):
    """Drop critic issues that are demonstrably false or that contradict an
    explicit user instruction.

    Two cases we handle:
    1. The Critic hallucinates (e.g. 'headline repeated 3x' with one <h1>).
    2. The user explicitly asked for something the Critic dislikes on
       aesthetic grounds (e.g. "make bg red" → Critic complains "red isn't
       in the ad palette"). User intent beats Critic aesthetic opinions.
    """
    from bs4 import BeautifulSoup
    from app.schemas import CriticReport
    try:
        soup = BeautifulSoup(patched_html, "lxml")
    except Exception:
        return critique

    h1_count = len(soup.find_all("h1"))
    instr = (user_instruction or "").lower()
    # Does the user's instruction mention a specific visual change the Critic
    # would normally veto? Grant the user veto-power back.
    user_demanded_color = any(
        w in instr for w in (
            "red", "blue", "green", "yellow", "orange", "purple",
            "pink", "black", "white", "grey", "gray", "retro",
            "color", "colour", "background", "accent",
        )
    )
    user_demanded_size = any(
        w in instr for w in ("bigger", "larger", "smaller", "bold", "big", "small")
    )

    kept = []
    for i in critique.issues:
        if i.kind == "duplicate_ghost" and h1_count <= 1:
            logger.info("critic: dropping duplicate_ghost (actual h1 count={})", h1_count)
            continue
        if user_demanded_color and i.kind == "color":
            logger.info("critic: dropping 'color' issue — user explicitly asked for it")
            continue
        if user_demanded_size and i.kind == "typography":
            logger.info("critic: dropping 'typography' issue — user explicitly asked for it")
            continue
        kept.append(i)

    verdict = critique.verdict
    if verdict != "ship" and not kept and critique.score >= 6:
        verdict = "ship"
    if verdict != "ship" and critique.score >= 7 and all(
        i.kind in ("typography", "color", "other") for i in kept
    ):
        verdict = "ship"
    # If the user explicitly asked for the thing the critic is complaining
    # about, we should ship regardless of score. Their intent is law.
    if (user_demanded_color or user_demanded_size) and critique.score >= 5 \
            and not any(i.kind in ("layout", "duplicate_ghost", "message_match",
                                   "cta_weakness", "hierarchy") for i in kept):
        verdict = "ship"

    return CriticReport(
        session_id=critique.session_id, version=critique.version,
        score=critique.score, issues=kept, verdict=verdict,
    )


def _map_kind(critic_kind: str) -> str:
    mapping = {
        "layout": "layout_broken",
        "typography": "other",
        "color": "contrast_fail",
        "hierarchy": "other",
        "message_match": "message_mismatch",
        "duplicate_ghost": "layout_broken",
        "cta_weakness": "missing_cta",
        "other": "other",
    }
    return mapping.get(critic_kind, "other")


async def _load_original_screenshot(session_id: UUID) -> bytes:
    client = sb.sb()
    if not client:
        return b""
    try:
        return client.storage.from_("screenshots").download(f"{session_id}/original.png")
    except Exception as e:
        logger.warning("original screenshot download failed: {}", e)
        return b""


async def _load_context(
    session_id: UUID,
) -> tuple[ExtractorOutput, str, str, PatchPlan | None, list[dict], bytes]:
    """Reload everything needed to drive a chat turn without re-scraping."""
    client = sb.sb()
    if not client:
        raise RuntimeError("Supabase not configured")

    s = client.table("sessions").select("landing_url, ad_path").eq(
        "id", str(session_id)).single().execute()
    landing_url = s.data["landing_url"]
    ad_path = s.data.get("ad_path") or ""

    ex = client.table("ad_extracts").select(
        "profile, page_profile, brand_context").eq("session_id", str(session_id)).single().execute()
    page_data = ex.data.get("page_profile") or {
        "hero": {}, "sections": [], "brand_palette": [], "copy_inventory": {},
    }
    extract = ExtractorOutput(
        ad=ex.data["profile"],
        page=page_data,
        brand=ex.data.get("brand_context") or {"snippets": []},
    )

    sc = client.table("scrapes").select("html").eq(
        "session_id", str(session_id)).single().execute()
    html = sc.data["html"]

    plans = client.table("patch_plans").select("version, plan").eq(
        "session_id", str(session_id)).order("version", desc=True).limit(1).execute()
    current_plan = PatchPlan(**plans.data[0]["plan"]) if plans.data else None

    msgs = client.table("chat_messages").select("role, content").eq(
        "session_id", str(session_id)).order("created_at").execute()
    history = [{"role": m["role"], "content": m["content"]} for m in (msgs.data or [])]

    # Ad image bytes — needed for the Critic.
    ad_bytes = b""
    if ad_path:
        try:
            # ad_path is stored as "ad-uploads/<session_id>/filename"
            bucket, _, rest = ad_path.partition("/")
            ad_bytes = client.storage.from_(bucket).download(rest)
        except Exception as e:
            logger.warning("ad image download failed: {}", e)

    return extract, html, landing_url, current_plan, history, ad_bytes
