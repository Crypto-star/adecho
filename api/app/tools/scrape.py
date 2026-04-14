"""Landing page scraping — Jina (fast) and Playwright (deep)."""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from agent_reach.channels.web import WebChannel
from bs4 import BeautifulSoup
from loguru import logger
from playwright.async_api import async_playwright


async def read_fast(url: str) -> str:
    """Jina Reader → clean markdown. Zero key needed. Best-effort."""
    try:
        return await asyncio.to_thread(WebChannel().read, url)
    except Exception as e:
        logger.warning("Jina read failed for {}: {}", url, e)
        return ""


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


_TOKENS_JS = r"""() => {
  const pick = (el, prop) => el ? getComputedStyle(el).getPropertyValue(prop).trim() : "";
  // Walk up the DOM to find the first ancestor with an opaque background.
  // Stripe's <body> is rgba(0,0,0,0) (transparent) — naively reading it
  // gives us "black" which makes black-on-black text invisible.
  const realBg = (el) => {
    let cur = el;
    for (let i = 0; i < 6 && cur; i++, cur = cur.parentElement) {
      const bg = getComputedStyle(cur).backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
    }
    return "rgb(255, 255, 255)";  // sensible web default
  };
  const h1 = document.querySelector("h1");
  const isButtonish = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    const hasBg = bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent";
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const wide = parseFloat(cs.width) > 80;
    const text = (el.innerText || "").trim().toLowerCase();
    const ctaWords = ["start", "sign", "get", "try", "join", "book", "buy", "free", "demo"];
    const hasCtaWord = ctaWords.some((w) => text.includes(w));
    return hasBg && pad >= 14 && wide && hasCtaWord;
  };
  const heroSection = h1 ? h1.closest("section, header, main, div") : null;
  const candidateRoots = [heroSection, document];
  let heroCta = null;
  for (const root of candidateRoots) {
    if (!root) continue;
    const links = Array.from(root.querySelectorAll("a, button"));
    heroCta = links.find(isButtonish) || null;
    if (heroCta) break;
  }
  const body = document.body;
  // Heading font comes from h1, body font from body.
  const tokens = {
    fonts: {
      heading: pick(h1, "font-family") || pick(body, "font-family"),
      body: pick(body, "font-family"),
    },
    colors: {
      bg: realBg(body),
      text: pick(h1, "color") || pick(body, "color"),
      muted: pick(document.querySelector("p"), "color"),
      brand_accent: pick(heroCta, "background-color") || pick(heroCta, "color"),
    },
    radius: pick(heroCta, "border-radius") || pick(h1, "border-radius") || "0.5rem",
    shadow: pick(heroCta, "box-shadow") || "0 4px 16px rgba(0,0,0,.08)",
    container_max_width: (() => {
      const hero = h1?.closest("section, div");
      return hero ? pick(hero, "max-width") || "1152px" : "1152px";
    })(),
    hero_padding_y: (() => {
      const hero = h1?.closest("section, div");
      return hero ? pick(hero, "padding-top") || "4rem" : "4rem";
    })(),
  };
  // Flatten "rgb()" colors to hex for readability downstream.
  const toHex = (c) => {
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return c;
    const [r,g,b] = [m[1],m[2],m[3]].map(x => Number(x).toString(16).padStart(2,"0"));
    return "#" + r + g + b;
  };
  for (const k of Object.keys(tokens.colors)) tokens.colors[k] = toHex(tokens.colors[k] || "");
  return tokens;
}"""


async def scrape_deep(url: str) -> dict[str, Any]:
    """Playwright → {html, palette, screenshot_png, title}.

    Resilient to transient `ERR_ABORTED`, bot-blocks, and slow first paints:
    - normalize URL scheme
    - real desktop UA + locale
    - two attempts: `domcontentloaded`, then `load`
    - on navigation error, still try to grab whatever the page rendered
    """
    url = _normalize_url(url)
    last_err: Exception | None = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await context.new_page()
        html = ""
        title = ""
        screenshot = b""
        try:
            for wait in ("domcontentloaded", "load"):
                try:
                    await page.goto(url, wait_until=wait, timeout=35000)
                    break
                except Exception as e:
                    last_err = e
                    logger.warning("scrape: goto({}) failed [{}]: {}", wait, type(e).__name__, e)
                    # Small backoff before retry
                    await page.wait_for_timeout(800)
            # Try to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(1200)
            html = await page.content()
            title = await page.title()
            try:
                screenshot = await page.screenshot(full_page=False, type="png")
            except Exception as e:
                logger.warning("scrape: screenshot failed: {}", e)
                screenshot = b""
            try:
                design_tokens = await page.evaluate(_TOKENS_JS)
            except Exception as e:
                logger.warning("scrape: design tokens eval failed: {}", e)
                design_tokens = {}
        finally:
            await browser.close()

    if not html:
        raise RuntimeError(
            f"Could not load page {url}: {last_err or 'unknown navigation error'}"
        )

    palette = extract_palette(html)
    return {
        "html": html,
        "title": title,
        "screenshot_png": screenshot,
        "palette": palette,
        "design_tokens": design_tokens or {},
    }


def extract_palette(html: str, top_n: int = 6) -> list[str]:
    """Quick-and-dirty palette: count hex colors in inline styles + style tags."""
    import re
    hexes = re.findall(r"#[0-9a-fA-F]{6}\b", html)
    return [c for c, _ in Counter(hexes).most_common(top_n)]


def build_page_profile(html: str, screenshot_path: str | None) -> dict[str, Any]:
    """Extract hero / sections / copy inventory from HTML (no LLM).

    Tags every element of interest with a unique `data-troopod-id` attribute,
    so every selector is guaranteed to match exactly one element downstream.
    Returns `_stamped_html` — callers must persist THIS as the scraped HTML
    (not the raw input) so the Builder operates on the same stamped DOM.
    """
    soup = BeautifulSoup(html, "lxml")

    counter = 0

    def stamp(tag) -> str:
        nonlocal counter
        existing = tag.get("data-troopod-id")
        if not existing:
            counter += 1
            existing = f"t{counter}"
            tag["data-troopod-id"] = existing
        return f"[data-troopod-id='{existing}']"

    # Hero heuristic: first <h1> and the first <a>/<button> after it.
    h1 = soup.find("h1")
    hero: dict[str, Any] = {}
    hero_container_selector: str | None = None
    if h1:
        hero["headline_text"] = _dedupe_repeated(h1.get_text(" ", strip=True))
        hero["headline_selector"] = stamp(h1)
        cta = _pick_hero_cta(h1)
        if cta:
            hero["cta_text"] = _dedupe_repeated(cta.get_text(" ", strip=True))
            hero["cta_selector"] = stamp(cta)
        container = _pick_hero_container(h1, cta)
        if container is not None and container.name != "[document]":
            hero_container_selector = stamp(container)

    # Copy inventory — text-bearing elements, capped + deduped for animation
    # text repeats.
    inventory: dict[str, str] = {}
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "a", "button", "span"]):
        txt = _dedupe_repeated(tag.get_text(" ", strip=True))
        if 3 < len(txt) < 240:
            sel = stamp(tag)
            if sel not in inventory:
                inventory[sel] = txt
        if len(inventory) >= 200:
            break

    sections = [
        {"selector": stamp(s), "role": s.name,
         "text_excerpt": s.get_text(" ", strip=True)[:180]}
        for s in soup.find_all(["section", "header", "footer"])[:12]
    ]

    return {
        "hero": hero,
        "hero_container_selector": hero_container_selector,
        "sections": sections,
        "brand_palette": extract_palette(html),
        "copy_inventory": inventory,
        "screenshot_path": screenshot_path,
        "_stamped_html": str(soup),
    }


def _dedupe_repeated(text: str) -> str:
    """Collapse animation-layer text triplication (word-level, not char-level).

    Many modern hero sections (Linear, Framer, Apple) render the same phrase
    N times via nested inline spans for cross-fade / stagger animations.
    BeautifulSoup's get_text() concatenates them, giving:
      "The product dev system for teams The product dev system for teams …"
    Which then gets copied verbatim into the new hero by the LLM.
    """
    s = " ".join((text or "").split())
    if not s:
        return s
    words = s.split(" ")
    w = len(words)
    # If the word sequence is exactly k copies of the first w/k words, keep one.
    for k in (5, 4, 3, 2):
        if w >= k * 2 and w % k == 0:
            seg = w // k
            first = words[:seg]
            if all(words[i * seg:(i + 1) * seg] == first for i in range(k)):
                return " ".join(first)
    return s


_CTA_WORDS = ("start", "sign up", "sign in", "get started", "get", "try",
              "join", "book", "buy", "free", "demo", "download", "subscribe")


def _pick_hero_cta(h1):
    """Pick the real primary CTA near the hero, not just 'the next link'.

    v0/Lovable-style heuristic: score each nearby <a>/<button> by
      + short, action-oriented copy (+2)
      + presence of CTA verb ("start", "sign up", "get started", …) (+3)
      + button tag (+1)
      - too-long text (marketing tagline / product name) (-2)
    Pick the highest-scoring element within the same containing section.
    Fallback to the first anchor/button after h1.
    """
    section = h1.find_parent(["section", "header", "main", "div"]) or h1.parent
    if section is None:
        return None
    candidates = section.find_all(["a", "button"], recursive=True)
    best, best_score = None, -999
    for el in candidates[:40]:
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text or len(text) > 60:
            continue
        t = text.lower()
        score = 0
        if any(w in t for w in _CTA_WORDS):
            score += 3
        if len(text) < 22:
            score += 2
        if el.name == "button":
            score += 1
        if "→" in text or "›" in text:
            score += 1
        if score > best_score:
            best, best_score = el, score
    if best is not None and best_score >= 2:
        return best
    # Fallback — old heuristic.
    return h1.find_next(lambda t: t.name in ("a", "button") and t.get_text(strip=True))


def _common_ancestor(a, b):
    """Deepest common ancestor of two BS4 nodes; None if not in same tree."""
    if a is None or b is None:
        return None
    ancestors = set()
    cur = a
    while cur is not None:
        ancestors.add(id(cur))
        cur = cur.parent
    cur = b
    while cur is not None:
        if id(cur) in ancestors:
            return cur
        cur = cur.parent
    return None


_HERO_CLASS_HINTS = ("hero", "banner", "landing", "masthead", "top", "lead")


def _pick_hero_container(h1, cta):
    """Pick a robust hero container for block surgery.

    Strategy (in priority order):
      1. Nearest ancestor <section>/<header>/<main> that contains the h1.
      2. Ancestor <div> whose class/id contains a hero-like hint word.
      3. First ancestor that contains h1 + at least one <p> AND one <a>/<button>.
      4. common_ancestor(h1, cta) — only if cta is present AND the resulting
         container still contains the h1 AND has enough 'meaningful content'.
      5. Fallback: h1's parent.

    This avoids the Stripe-style failure where a sibling modal's CTA drags
    the common ancestor into a tiny container, causing the replace_section
    to render inside a 40px-wide column.
    """
    if h1 is None:
        return None

    # 1. Semantic landmark
    for tag in ("section", "header", "main", "article"):
        parent = h1.find_parent(tag)
        if parent is not None:
            return parent

    # 2. Hero-ish class/id hint
    cur = h1.parent
    for _ in range(6):
        if cur is None or cur.name in (None, "[document]"):
            break
        cls = " ".join(cur.get("class") or []).lower()
        idv = (cur.get("id") or "").lower()
        if any(h in cls or h in idv for h in _HERO_CLASS_HINTS):
            return cur
        cur = cur.parent

    # 3. Structural: first ancestor that contains h1 + p + (a|button)
    cur = h1.parent
    for _ in range(6):
        if cur is None or cur.name in (None, "[document]"):
            break
        has_p = cur.find("p") is not None
        has_action = cur.find(["a", "button"]) is not None
        if has_p and has_action:
            return cur
        cur = cur.parent

    # 4. Common-ancestor fallback — ONLY if it passes sanity checks
    if cta is not None:
        c = _common_ancestor(h1, cta)
        if c is not None and c.name not in (None, "[document]"):
            # Must still contain the hero h1 and at least one <p>
            if c.find("h1") is h1 and c.find("p") is not None:
                return c

    # 5. Parent fallback
    return h1.parent


def _selector_for(tag) -> str:
    """Stable-ish selector: id > data-attr > nth-of-type path (bounded depth)."""
    if tag.get("id"):
        return f"#{tag['id']}"
    # Walk up at most 4 ancestors to build a path.
    parts: list[str] = []
    cur = tag
    depth = 0
    while cur and cur.name and depth < 4:
        name = cur.name
        if cur.get("id"):
            parts.insert(0, f"{name}#{cur['id']}")
            break
        siblings = [s for s in cur.parent.find_all(name, recursive=False)] if cur.parent else []
        if len(siblings) > 1:
            idx = siblings.index(cur) + 1
            parts.insert(0, f"{name}:nth-of-type({idx})")
        else:
            parts.insert(0, name)
        cur = cur.parent
        depth += 1
    return " > ".join(parts)
