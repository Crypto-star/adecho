"""Builder — applies PatchPlan to scraped HTML. Deterministic; LLM only for synthesis."""
from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.schemas import PatchPlan, RenderArtifact
from app.services import supabase_client as sb
from app.tools.patcher import apply_patch


async def run(session_id: UUID, html: str, plan: PatchPlan, base_url: str) -> RenderArtifact:
    with sb.log_agent(session_id, "builder", version=plan.version) as log:
        log.set(input={"plan_version": plan.version, "html_len": len(html)})
        artifact = apply_patch(html, plan, base_url)
        sb.save_render(session_id, artifact.version, artifact.patched_html)
        log.set(output={
            "changes_applied": artifact.changes_applied,
            "changes_skipped": artifact.changes_skipped,
        })
        logger.info(
            "Builder v{} applied={} skipped={}",
            artifact.version, len(artifact.changes_applied), len(artifact.changes_skipped),
        )
        return artifact
