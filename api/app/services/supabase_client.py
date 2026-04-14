"""Supabase service-role client + thin persistence helpers."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from loguru import logger
from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def sb() -> Client | None:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        logger.warning("Supabase env not set — running in memory-only mode")
        return None
    return create_client(s.supabase_url, s.supabase_service_role_key)


# ── Session lifecycle ───────────────────────────────────────────────────
def create_session(landing_url: str, ad_path: str | None) -> str:
    client = sb()
    if not client:
        # Memory-only fallback for local dev without Supabase
        import uuid
        return str(uuid.uuid4())
    row = client.table("sessions").insert({
        "landing_url": landing_url,
        "ad_path": ad_path,
        "status": "created",
    }).execute()
    return row.data[0]["id"]


def update_session(session_id: str | UUID, **fields: Any) -> None:
    client = sb()
    if not client:
        return
    client.table("sessions").update(fields).eq("id", str(session_id)).execute()


# ── Artifacts ───────────────────────────────────────────────────────────
def save_scrape(session_id: str | UUID, *, html: str, markdown: str,
                screenshot_path: str | None, palette: list[str]) -> None:
    client = sb()
    if not client:
        return
    client.table("scrapes").upsert({
        "session_id": str(session_id),
        "html": html,
        "markdown": markdown,
        "screenshot_path": screenshot_path,
        "palette": palette,
    }).execute()


def save_ad_extract(session_id: str | UUID, profile: dict, brand: dict,
                    page_profile: dict | None = None) -> None:
    client = sb()
    if not client:
        return
    client.table("ad_extracts").upsert({
        "session_id": str(session_id),
        "profile": profile,
        "brand_context": brand,
        "page_profile": page_profile or {},
    }).execute()


def save_patch_plan(session_id: str | UUID, version: int, plan: dict) -> None:
    client = sb()
    if not client:
        return
    client.table("patch_plans").upsert({
        "session_id": str(session_id),
        "version": version,
        "plan": plan,
    }).execute()


def save_render(session_id: str | UUID, version: int, patched_html: str,
                screenshot_path: str | None = None) -> None:
    client = sb()
    if not client:
        return
    client.table("renders").upsert({
        "session_id": str(session_id),
        "version": version,
        "patched_html": patched_html,
        "screenshot_path": screenshot_path,
    }).execute()


def save_verifier_report(session_id: str | UUID, version: int, passed: bool,
                         issues: list[dict], screenshot_path: str | None) -> None:
    client = sb()
    if not client:
        return
    client.table("verifier_reports").upsert({
        "session_id": str(session_id),
        "version": version,
        "passed": passed,
        "issues": issues,
        "screenshot_path": screenshot_path,
    }).execute()


def save_chat(session_id: str | UUID, role: str, content: str,
              plan_version: int | None = None) -> None:
    client = sb()
    if not client:
        return
    client.table("chat_messages").insert({
        "session_id": str(session_id),
        "role": role,
        "content": content,
        "plan_version": plan_version,
    }).execute()


# ── Agent logging ───────────────────────────────────────────────────────
@contextmanager
def log_agent(session_id: str | UUID, agent: str, version: int | None = None):
    """Context manager: `with log_agent(...) as log: log.set(input=..., output=...)`"""
    start = time.perf_counter()
    record: dict[str, Any] = {"input": None, "output": None, "error": None}

    class _L:
        def set(self, **kw: Any) -> None:
            record.update(kw)

    holder = _L()
    try:
        yield holder
    except Exception as e:
        record["error"] = str(e)
        raise
    finally:
        client = sb()
        if client:
            try:
                client.table("agent_logs").insert({
                    "session_id": str(session_id),
                    "agent": agent,
                    "version": version,
                    "input": record["input"],
                    "output": record["output"],
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                    "error": record["error"],
                }).execute()
            except Exception as e:
                logger.warning("agent_logs insert failed: {}", e)


# ── Storage ─────────────────────────────────────────────────────────────
def upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> str:
    client = sb()
    if not client:
        return f"local://{bucket}/{path}"
    client.storage.from_(bucket).upload(
        path, data, {"content-type": content_type, "upsert": "true"}
    )
    return f"{bucket}/{path}"
