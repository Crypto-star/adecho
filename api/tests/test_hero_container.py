"""Regression: hero container selection must be robust to misleading
sibling CTAs (Stripe-style), and must prefer semantic landmarks."""
from bs4 import BeautifulSoup

from app.tools.scrape import _pick_hero_container


def test_prefers_semantic_section():
    html = """<body>
      <header><h2>header</h2></header>
      <main>
        <section>
          <h1>Real hero headline</h1>
          <p>Subcopy</p>
          <a href='/signup'>Start now</a>
        </section>
      </main>
    </body>"""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    cta = soup.find("a")
    c = _pick_hero_container(h1, cta)
    assert c.name == "section"


def test_prefers_section_over_common_ancestor_with_wrong_cta():
    # Stripe-style: h1 in <main>, the 'cta' we pass is in an <aside> sidebar.
    # Common ancestor is <body>, which would be disastrous. Semantic
    # <section> wins.
    html = """<body>
      <main>
        <section class='hero-banner'>
          <h1>Real hero</h1>
          <p>Sub</p>
          <a>Real CTA</a>
        </section>
      </main>
      <aside>
        <button>Request an invite</button>
      </aside>
    </body>"""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    wrong_cta = soup.select_one("aside button")
    c = _pick_hero_container(h1, wrong_cta)
    assert c.name == "section" and "hero-banner" in c.get("class")


def test_uses_hero_class_hint_when_no_semantic_landmark():
    html = """<body>
      <div class="hero-wrapper">
        <div>
          <h1>Hi</h1>
          <p>Sub</p>
          <a>Go</a>
        </div>
      </div>
    </body>"""
    soup = BeautifulSoup(html, "lxml")
    c = _pick_hero_container(soup.find("h1"), soup.find("a"))
    # Walks up; finds .hero-wrapper by class hint before using common-ancestor.
    assert c.name == "div" and "hero-wrapper" in c.get("class")


def test_structural_fallback_when_no_landmark_or_hint():
    html = """<body>
      <div id="root">
        <div>
          <h1>Hi</h1>
          <p>Sub</p>
          <a>Go</a>
        </div>
      </div>
    </body>"""
    soup = BeautifulSoup(html, "lxml")
    c = _pick_hero_container(soup.find("h1"), soup.find("a"))
    # First ancestor containing h1 + p + action.
    assert c.find("h1") is not None and c.find("p") is not None
