"""Regression: when refining, the Strategist receives a PRESERVE_VERBATIM
block so it doesn't revert to Linear's original headline text.
"""
from uuid import uuid4

from app.agents.strategist import _extract_current_hero_copy
from app.schemas import Change, PatchPlan


def test_extracts_from_replace_section_payload():
    p = PatchPlan(session_id=uuid4(), version=1, changes=[
        Change(
            selector="[data-troopod-id='t3']",
            op="replace_section",
            payload=(
                "<div>"
                "<h1>Ship faster. Built for engineers.</h1>"
                "<p>Keyboard-first issue tracking, no bloat.</p>"
                "<a href='#'>Start free →</a>"
                "</div>"
            ),
            rationale="x", source="ad",
        )
    ])
    out = _extract_current_hero_copy(p)
    assert out == {
        "headline": "Ship faster. Built for engineers.",
        "subheadline": "Keyboard-first issue tracking, no bloat.",
        "cta_text": "Start free →",
    }


def test_returns_none_when_no_replace_section():
    p = PatchPlan(session_id=uuid4(), version=1, changes=[
        Change(
            selector="[data-troopod-id='t2']",
            op="replace_text", payload="x",
            rationale="y", source="ad",
        )
    ])
    assert _extract_current_hero_copy(p) is None


def test_none_plan():
    assert _extract_current_hero_copy(None) is None
