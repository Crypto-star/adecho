"""Verifier — screenshots the rendered page and checks against ad + source rules."""
from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.schemas import ExtractorOutput, Issue, PatchPlan, RenderArtifact, VerifierReport
from app.services import supabase_client as sb
from app.tools.vision import render_screenshot


async def run(session_id: UUID, render: RenderArtifact, plan: PatchPlan,
              extract: ExtractorOutput, base_url: str) -> VerifierReport:
    with sb.log_agent(session_id, "verifier", version=render.version) as log:
        screenshot = await render_screenshot(render.patched_html)
        screenshot_path = sb.upload_bytes(
            "screenshots", f"{session_id}/v{render.version}.png",
            screenshot, "image/png",
        )

        issues: list[Issue] = []

        # Rule 1: every non-ad/page change must cite exa or a CRO principle.
        for ch in plan.changes:
            if ch.source not in ("ad", "page", "exa", "cro_principle"):
                issues.append(Issue(
                    severity="blocker", kind="hallucinated_claim",
                    detail=f"change with invalid source={ch.source}",
                    selector=ch.selector,
                ))

        # Rule 2: if plan cites exa but brand snippets empty, warn.
        cited_exa = any(ch.source == "exa" for ch in plan.changes)
        if cited_exa and not extract.brand.snippets:
            issues.append(Issue(
                severity="warn", kind="hallucinated_claim",
                detail="Plan cites Exa sources but brand context has no snippets.",
            ))

        # Rule 3: too many skipped selectors → likely broken plan.
        if render.changes_skipped and len(render.changes_skipped) > len(render.changes_applied):
            issues.append(Issue(
                severity="warn", kind="layout_broken",
                detail=f"More skipped ({len(render.changes_skipped)}) than applied "
                       f"({len(render.changes_applied)}).",
            ))

        passed = not any(i.severity == "blocker" for i in issues)
        report = VerifierReport(
            session_id=session_id, version=render.version,
            passed=passed, issues=issues, screenshot_path=screenshot_path,
        )
        sb.save_verifier_report(
            session_id, render.version, passed,
            [i.model_dump() for i in issues], screenshot_path,
        )
        log.set(output=report.model_dump(mode="json"))
        logger.info("Verifier v{} passed={} issues={}", render.version, passed, len(issues))
        return report


