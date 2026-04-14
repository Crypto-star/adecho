"""Session + pipeline routes."""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import HTMLResponse
from loguru import logger

from app.agents import pipeline
from app.schemas import ChatRequest, CreateSessionResponse
from app.services import supabase_client as sb

router = APIRouter()


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    background: BackgroundTasks,
    landing_url: str = Form(...),
    ad: UploadFile = File(...),
) -> CreateSessionResponse:
    ad_bytes = await ad.read()
    if not ad_bytes:
        raise HTTPException(400, "Empty ad upload")

    # Upload ad to storage (if Supabase configured); create session row.
    # We don't know session_id yet — create first, then upload under its id.
    session_id = sb.create_session(landing_url=landing_url, ad_path=None)
    ad_path = sb.upload_bytes(
        "ad-uploads", f"{session_id}/{ad.filename or 'ad.png'}",
        ad_bytes, ad.content_type or "image/png",
    )
    sb.update_session(session_id, ad_path=ad_path)

    # Kick pipeline in background so the POST returns fast.
    background.add_task(
        _run_safe, UUID(session_id), ad_bytes, ad.content_type or "image/png", landing_url,
    )
    return CreateSessionResponse(session_id=UUID(session_id), status="created")


async def _run_safe(session_id: UUID, ad_bytes: bytes, mime: str, landing_url: str) -> None:
    try:
        await pipeline.run_initial(session_id, ad_bytes, mime, landing_url)
    except Exception as e:
        logger.exception("Pipeline failed for {}: {}", session_id, e)
        try:
            sb.update_session(session_id, status="failed", error=str(e))
        except Exception as e2:
            logger.error("also failed to record failure state: {}", e2)


def _no_cache(resp: HTMLResponse) -> HTMLResponse:
    """Prevent browsers and iframes from caching renders — versions change often."""
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@router.get("/render/{session_id}", response_class=HTMLResponse)
async def render(session_id: UUID, version: int | None = None) -> Response:
    client = sb.sb()
    if not client:
        raise HTTPException(503, "Supabase not configured")
    q = client.table("renders").select("patched_html, version").eq("session_id", str(session_id))
    if version is not None:
        q = q.eq("version", version)
    r = q.order("version", desc=True).limit(1).execute()
    if not r.data:
        raise HTTPException(404, "No render yet")
    return _no_cache(HTMLResponse(r.data[0]["patched_html"]))


@router.get("/render/{session_id}/original.png")
async def render_original_png(session_id: UUID) -> Response:
    """Stream the original page screenshot captured during extraction.

    This is the ground-truth 'Original' view: exactly what the user's page
    looked like at scrape time, including JS-rendered content. Much more
    reliable than reconstructing HTML without scripts in an iframe, where
    animations / hydration-only content silently breaks.
    """
    client = sb.sb()
    if not client:
        raise HTTPException(503, "Supabase not configured")
    try:
        data = client.storage.from_("screenshots").download(f"{session_id}/original.png")
    except Exception:
        raise HTTPException(404, "No original screenshot yet")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/render/{session_id}/original", response_class=HTMLResponse)
async def render_original(session_id: UUID) -> Response:
    """Serve the scraped HTML with <base href> injected + scripts stripped, so
    the Original tab can be iframed even when the real site sets X-Frame-Options
    to block embedding."""
    client = sb.sb()
    if not client:
        raise HTTPException(503, "Supabase not configured")
    sc = client.table("scrapes").select("html").eq("session_id", str(session_id)).single().execute()
    if not sc.data:
        raise HTTPException(404, "No scrape yet")
    ss = client.table("sessions").select("landing_url").eq("id", str(session_id)).single().execute()
    base_url = ss.data["landing_url"]

    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    soup = BeautifulSoup(sc.data["html"], "lxml")
    head = soup.head or soup.new_tag("head")
    if not soup.head:
        (soup.html or soup).insert(0, head)
    if not head.find("base"):
        p = urlparse(base_url)
        head.insert(0, soup.new_tag("base", href=f"{p.scheme}://{p.netloc}/"))
    # Same script/prefetch stripping as the personalized render so the two
    # tabs are apples-to-apples and the iframe console stays quiet.
    for s in soup.find_all("script"):
        s.decompose()
    for l in soup.find_all("link"):
        rel = " ".join(l.get("rel") or []).lower()
        if rel in ("manifest", "prefetch", "preload", "modulepreload", "dns-prefetch"):
            l.decompose()
    return _no_cache(HTMLResponse(str(soup)))


@router.post("/chat", status_code=202)
async def chat(req: ChatRequest, background: BackgroundTasks) -> dict:
    """Every chat turn runs the SAME full pipeline as the initial pass.

    We return 202 Accepted immediately (user message saved so Realtime pushes
    it to the pane) and run the Strategist → Builder → Verifier → Critic loop
    in the background. The assistant reply flows back through Supabase
    Realtime when it's ready — which avoids the 30s Next.js proxy timeout.
    """
    client = sb.sb()
    if not client:
        raise HTTPException(503, "Supabase not configured")

    # Save the user message synchronously so the FE sees it immediately.
    sb.save_chat(req.session_id, "user", req.message)
    background.add_task(_run_chat_turn_safe, req.session_id, req.message)
    return {"session_id": str(req.session_id), "status": "processing"}


async def _run_chat_turn_safe(session_id: UUID, message: str) -> None:
    try:
        result = await pipeline.run_turn(session_id, message)
    except Exception as e:
        logger.exception("Chat turn failed for {}: {}", session_id, e)
        try:
            sb.save_chat(
                session_id, "assistant",
                f"Sorry — I hit an error applying that change. "
                f"({type(e).__name__}: {str(e)[:180]})",
            )
            sb.update_session(session_id, status="ready")  # don't leave stuck
        except Exception as e2:
            logger.error("also failed to record chat failure: {}", e2)
        return

    issue_hint = ""
    if result.critic_verdict != "ship" and result.critic_issues:
        top = result.critic_issues[0]
        issue_hint = f" Critic flagged: {top.detail[:120]}"
    assistant_msg = (
        f"Applied — v{result.plan.version}, critic {result.critic_score}/10"
        f" ({result.critic_verdict}).{issue_hint}"
    )
    sb.save_chat(session_id, "assistant", assistant_msg,
                 plan_version=result.plan.version)


@router.get("/sessions/{session_id}")
async def get_session(session_id: UUID) -> dict:
    client = sb.sb()
    if not client:
        raise HTTPException(503, "Supabase not configured")
    r = client.table("sessions").select("*").eq("id", str(session_id)).single().execute()
    if not r.data:
        raise HTTPException(404, "Session not found")
    return r.data
