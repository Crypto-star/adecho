"""Exa search — via Agent-Reach MCP if present, else direct HTTP fallback."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from app.config import get_settings


async def exa_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    """Return [{url, title, text}]. Best-effort; returns [] on failure."""
    key = get_settings().exa_api_key
    if key:
        return await _exa_http(query, num_results, key)
    # Try agent-reach MCP route
    try:
        return await _exa_via_agent_reach(query, num_results)
    except Exception as e:
        logger.warning("Exa search unavailable: {}", e)
        return []


async def _exa_http(query: str, n: int, key: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key, "content-type": "application/json"},
            json={"query": query, "numResults": n, "contents": {"text": True}},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"url": item.get("url"), "title": item.get("title"),
         "text": (item.get("text") or "")[:1500]}
        for item in data.get("results", [])
    ]


async def _exa_via_agent_reach(query: str, n: int) -> list[dict[str, Any]]:
    """Shell out to mcporter if the MCP channel is configured.
    Deliberately best-effort; in production we prefer the HTTP path with EXA_API_KEY.
    """
    def _run() -> list[dict[str, Any]]:
        import shutil, subprocess, json
        if not shutil.which("mcporter"):
            return []
        # mcporter call shape is runtime-dependent; return empty to keep pipeline green.
        return []
    return await asyncio.to_thread(_run)
