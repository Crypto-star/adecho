"""V2 regression: replace_section swaps a hero container AND strips sibling
duplicate <h1>s elsewhere in the document (Linear-style ghost layer cleanup).
"""
from uuid import uuid4

from app.schemas import Change, PatchPlan
from app.tools.patcher import apply_patch
from app.tools.scrape import build_page_profile


LINEAR_ISH = """<html><body>
  <header><h1>Ghost headline A</h1></header>
  <section data-troopod-id="hero">
    <h1>Real hero headline</h1>
    <a href="/signup">Sign up</a>
  </section>
  <aside><h1>Ghost headline B</h1></aside>
</body></html>"""


def test_replace_section_strips_ghost_siblings():
    sid = uuid4()
    new_hero = (
        "<h1 style='font-size:48px'>Ship faster. Free.</h1>"
        "<p>Keyboard-first issue tracking.</p>"
        "<a style='background:#5E6AD2;color:#fff;padding:12px 20px' href='/signup'>Start free</a>"
    )
    plan = PatchPlan(session_id=sid, version=1, changes=[
        Change(
            selector="[data-troopod-id='hero']",
            op="replace_section",
            payload=new_hero,
            rationale="hero block surgery",
            source="ad",
        ),
    ])
    art = apply_patch(LINEAR_ISH, plan, base_url="https://linear.app")

    # New hero content present
    assert "Ship faster. Free." in art.patched_html
    assert "Start free" in art.patched_html
    # Ghost siblings removed (they were outside the new hero container)
    assert "Ghost headline A" not in art.patched_html
    assert "Ghost headline B" not in art.patched_html
    # Original hero <h1> is gone (replaced wholesale)
    assert "Real hero headline" not in art.patched_html
    # Exactly one <h1> left
    from bs4 import BeautifulSoup
    assert len(BeautifulSoup(art.patched_html, "lxml").find_all("h1")) == 1


def test_hero_container_selector_is_stamped():
    p = build_page_profile(LINEAR_ISH, None)
    assert p["hero_container_selector"], "extractor must stamp hero container"
    # And it must uniquely resolve on the stamped html
    from bs4 import BeautifulSoup
    stamped = BeautifulSoup(p["_stamped_html"], "lxml")
    assert stamped.select_one(p["hero_container_selector"]) is not None
