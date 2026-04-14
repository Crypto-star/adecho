"""Smoke tests that do not require network or API keys."""
from uuid import uuid4

from app.schemas import Change, PatchPlan
from app.tools.patcher import apply_patch
from app.tools.scrape import build_page_profile, extract_palette


HTML = """<!doctype html><html><head><title>T</title>
<style>.btn{background:#ff3366;color:#fff}</style></head>
<body>
 <header><nav><a href="/">Home</a></nav></header>
 <section id="hero">
   <h1>Old headline</h1>
   <p>Old subcopy about the product.</p>
   <a class="btn" href="/signup">Sign up</a>
 </section>
 <section id="features">
   <h2>Features</h2>
   <ul><li>Fast</li><li>Cheap</li><li>Good</li></ul>
 </section>
 <script src="https://www.google-analytics.com/analytics.js"></script>
</body></html>"""


def test_palette_extraction():
    p = extract_palette(HTML)
    assert "#ff3366" in [c.lower() for c in p]


def test_page_profile_builds():
    prof = build_page_profile(HTML, screenshot_path=None)
    assert prof["hero"]["headline_text"] == "Old headline"
    assert any("Fast" in v or "Features" in v for v in prof["copy_inventory"].values())


def test_apply_patch_replaces_and_skips():
    sid = uuid4()
    plan = PatchPlan(
        session_id=sid, version=1, accent_color="#4f46e5",
        changes=[
            Change(selector="#hero h1", op="replace_text",
                   payload="New headline from ad", rationale="message match",
                   source="ad"),
            Change(selector=".btn", op="replace_text",
                   payload="Get 50% off", rationale="match ad CTA",
                   source="ad"),
            Change(selector="#does-not-exist", op="replace_text",
                   payload="nope", rationale="miss", source="ad"),
        ],
        new_modules=[{"position": "body_start",
                      "html": "<div id='urgency'>Ends tonight</div>"}],
    )
    art = apply_patch(HTML, plan, base_url="https://example.com/path")
    assert "New headline from ad" in art.patched_html
    assert "Get 50% off" in art.patched_html
    assert "Ends tonight" in art.patched_html
    assert "google-analytics" not in art.patched_html       # stripped
    assert "<base" in art.patched_html                      # base href injected
    assert art.changes_applied == ["#hero h1", ".btn"]
    assert art.changes_skipped == ["#does-not-exist"]


def test_schema_roundtrip():
    sid = uuid4()
    plan = PatchPlan(session_id=sid, version=1)
    assert plan.model_dump(mode="json")["session_id"] == str(sid)
