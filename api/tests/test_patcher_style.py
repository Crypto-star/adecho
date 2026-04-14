"""Regression: set_style accepts both dict and CSS-text payloads.

(The old refiner-merge dedup test was removed — the unified pipeline now has
the Strategist produce a FRESH full plan each turn, so duplicate changes on
the same (selector, op) aren't structurally possible anymore.)
"""
from uuid import uuid4

from app.schemas import Change, PatchPlan
from app.tools.patcher import apply_patch


HTML = "<html><body><a data-troopod-id='t2'>Old</a></body></html>"


def test_set_style_accepts_css_text():
    plan = PatchPlan(session_id=uuid4(), version=1, changes=[
        Change(selector="[data-troopod-id='t2']", op="set_style",
               payload="background-color: #6A67E0; color: white",
               rationale="x", source="ad"),
    ])
    art = apply_patch(HTML, plan, base_url="https://x.com")
    assert art.changes_skipped == []
    assert "background-color: #6A67E0" in art.patched_html
    assert "color: white" in art.patched_html


def test_set_style_accepts_dict():
    plan = PatchPlan(session_id=uuid4(), version=1, changes=[
        Change(selector="[data-troopod-id='t2']", op="set_style",
               payload={"background-color": "#000"},
               rationale="x", source="ad"),
    ])
    art = apply_patch(HTML, plan, base_url="https://x.com")
    assert art.changes_skipped == []
    assert "background-color: #000" in art.patched_html


