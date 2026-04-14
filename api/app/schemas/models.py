"""Pydantic I/O contracts — shared across agents and API layer.

These mirror the Design.md specs; keep them in lockstep with /docs/design/*.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


SessionStatus = Literal[
    "created", "extracting", "strategizing", "building",
    "verifying", "ready", "failed",
]


# ── Extractor ────────────────────────────────────────────────────────────
class AdProfile(BaseModel):
    offer: str
    value_prop: str
    tone: Literal["bold", "friendly", "professional", "playful", "urgent", "premium"]
    audience: str
    visual_style: dict[str, Any] = Field(
        description="{palette: [hex], typography: str, mood: str}"
    )
    claims: list[str] = Field(default_factory=list)
    cta_text: str | None = None


class DesignTokens(BaseModel):
    fonts: dict[str, str] = Field(default_factory=dict)      # heading, body
    colors: dict[str, str] = Field(default_factory=dict)     # bg, text, muted, brand_accent
    radius: str = "0.5rem"
    shadow: str = "0 4px 16px rgba(0,0,0,.08)"
    container_max_width: str = "1152px"
    hero_padding_y: str = "4rem"


class PageProfile(BaseModel):
    hero: dict[str, Any]
    sections: list[dict[str, Any]] = Field(default_factory=list)
    brand_palette: list[str] = Field(default_factory=list)
    copy_inventory: dict[str, str] = Field(default_factory=dict)
    screenshot_path: str | None = None
    hero_container_selector: str | None = None   # deepest common ancestor of hero h1+CTA
    design_tokens: DesignTokens = Field(default_factory=DesignTokens)


class BrandSnippet(BaseModel):
    source_url: str
    text: str
    fetched_at: str


class BrandContext(BaseModel):
    snippets: list[BrandSnippet] = Field(default_factory=list)


class ExtractorOutput(BaseModel):
    ad: AdProfile
    page: PageProfile
    brand: BrandContext = Field(default_factory=BrandContext)


# ── Strategist ───────────────────────────────────────────────────────────
class Change(BaseModel):
    selector: str
    op: Literal[
        "replace_text", "replace_html", "replace_section",
        "set_attr", "set_style",
        "insert_after", "insert_before", "remove",
    ]
    payload: str | dict[str, Any]
    rationale: str
    source: Literal["ad", "page", "exa", "cro_principle"]


class PatchPlan(BaseModel):
    session_id: UUID
    version: int
    accent_color: str | None = None
    changes: list[Change] = Field(default_factory=list, max_length=20)
    new_modules: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


# ── Builder ──────────────────────────────────────────────────────────────
class RenderArtifact(BaseModel):
    session_id: UUID
    version: int
    patched_html: str
    changes_applied: list[str] = Field(default_factory=list)
    changes_skipped: list[str] = Field(default_factory=list)


# ── Verifier ─────────────────────────────────────────────────────────────
class Issue(BaseModel):
    severity: Literal["blocker", "warn"]
    kind: Literal[
        "layout_broken", "message_mismatch", "hallucinated_claim",
        "missing_cta", "contrast_fail", "other",
    ]
    detail: str
    selector: str | None = None


class VerifierReport(BaseModel):
    session_id: UUID
    version: int
    passed: bool
    issues: list[Issue] = Field(default_factory=list)
    screenshot_path: str | None = None


# ── Critic ───────────────────────────────────────────────────────────────
class CriticIssue(BaseModel):
    kind: Literal["layout", "typography", "color", "hierarchy",
                  "message_match", "duplicate_ghost", "cta_weakness", "other"]
    detail: str
    suggested_selector: str | None = None
    suggested_fix: str | None = None


class CriticReport(BaseModel):
    session_id: UUID
    version: int
    score: int = Field(ge=1, le=10)
    issues: list[CriticIssue] = Field(default_factory=list)
    verdict: Literal["ship", "refine", "rebuild"]


# ── API request/response ─────────────────────────────────────────────────
class CreateSessionResponse(BaseModel):
    session_id: UUID
    status: SessionStatus


class RunRequest(BaseModel):
    session_id: UUID


class ChatRequest(BaseModel):
    session_id: UUID
    message: str
