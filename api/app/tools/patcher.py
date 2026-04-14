"""Apply a PatchPlan to scraped HTML via BeautifulSoup — pure code, no LLM."""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.schemas import Change, PatchPlan, RenderArtifact


def apply_patch(html: str, plan: PatchPlan, base_url: str) -> RenderArtifact:
    soup = BeautifulSoup(html, "lxml")

    # Inject <base href> so relative assets keep resolving against the original domain.
    head = soup.head or soup.new_tag("head")
    if not soup.head:
        (soup.html or soup).insert(0, head)
    if not head.find("base"):
        base_tag = soup.new_tag("base", href=_root(base_url))
        head.insert(0, base_tag)

    # Accent color via CSS variable at the end of <head>.
    if plan.accent_color:
        style = soup.new_tag("style")
        style.string = (
            f":root {{ --troopod-accent: {plan.accent_color}; }}\n"
            f"[data-troopod-accent] {{ background-color: var(--troopod-accent) !important; "
            f"color: #fff !important; }}"
        )
        head.append(style)

    applied: list[str] = []
    skipped: list[str] = []

    for ch in plan.changes:
        target = soup.select_one(ch.selector)
        if target is None:
            skipped.append(ch.selector)
            continue
        try:
            _apply_change(soup, target, ch)
            applied.append(ch.selector)
        except Exception:
            skipped.append(ch.selector)

    # Inject new_modules (urgency bars, trust badges, …). Each: {position, html}.
    for mod in plan.new_modules or []:
        pos = mod.get("position", "body_start")
        frag = BeautifulSoup(mod.get("html", ""), "lxml")
        nodes = list(frag.body.children) if frag.body else list(frag.children)
        if pos == "body_start" and soup.body:
            for n in reversed(nodes):
                soup.body.insert(0, n)
        elif pos == "body_end" and soup.body:
            for n in nodes:
                soup.body.append(n)

    # Strip ALL <script> tags. The iframe is a visual preview, not a functional SPA.
    # This also prevents the hosted site's client-side router (e.g. Next.js) from
    # hydrating and running RSC prefetches against our dev-server origin, which
    # floods the console with 404s.
    for s in soup.find_all("script"):
        s.decompose()
    # Disable service workers / link prefetch that fire without scripts, too.
    for l in soup.find_all("link"):
        rel = " ".join(l.get("rel") or []).lower()
        if rel in ("manifest", "prefetch", "preload", "modulepreload", "dns-prefetch"):
            l.decompose()

    return RenderArtifact(
        session_id=plan.session_id,
        version=plan.version,
        patched_html=str(soup),
        changes_applied=applied,
        changes_skipped=skipped,
    )


def _apply_change(soup: BeautifulSoup, target, ch: Change) -> None:
    if ch.op == "replace_text":
        target.clear()
        target.append(str(ch.payload))
    elif ch.op == "replace_html":
        frag = BeautifulSoup(str(ch.payload), "lxml")
        target.clear()
        children = list(frag.body.children) if frag.body else list(frag.children)
        for c in children:
            target.append(c)
    elif ch.op == "replace_section":
        # v2 block-surgery: replace the container's children AND kill any
        # sibling duplicate <h1>s elsewhere in the document (Linear-style
        # animation-layer ghosts). Same authoring contract as replace_html but
        # we also strip same-tag siblings so the new hero stands alone.
        frag = BeautifulSoup(str(ch.payload), "lxml")
        target.clear()
        children = list(frag.body.children) if frag.body else list(frag.children)
        for c in children:
            target.append(c)
        # Remove every <h1> in the document that is NOT inside the new target.
        for stray in list(soup.find_all("h1")):
            if stray is target or target in list(stray.parents):
                continue
            stray.decompose()
    elif ch.op == "set_attr":
        assert isinstance(ch.payload, dict)
        for k, v in ch.payload.items():
            target[k] = v
    elif ch.op == "set_style":
        # Accept either dict ({color: "#fff"}) or CSS-text ("color: #fff; bg: red").
        # LLMs routinely return the latter; tolerating both removes a whole class
        # of silent-skip bugs.
        if isinstance(ch.payload, dict):
            new_rules = {str(k).strip(): str(v).strip() for k, v in ch.payload.items()}
        elif isinstance(ch.payload, str):
            new_rules = {}
            for chunk in ch.payload.split(";"):
                if ":" in chunk:
                    k, v = chunk.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k and v:
                        new_rules[k] = v
        else:
            raise TypeError(f"set_style payload must be dict or str, got {type(ch.payload)}")
        existing = target.get("style", "")
        parts = [p.strip() for p in existing.split(";") if p.strip()]
        for k, v in new_rules.items():
            parts = [p for p in parts if not p.startswith(f"{k}:")]
            parts.append(f"{k}: {v}")
        target["style"] = "; ".join(parts)
    elif ch.op == "insert_after":
        frag = BeautifulSoup(str(ch.payload), "lxml")
        nodes = list(frag.body.children) if frag.body else list(frag.children)
        for n in reversed(nodes):
            target.insert_after(n)
    elif ch.op == "insert_before":
        frag = BeautifulSoup(str(ch.payload), "lxml")
        nodes = list(frag.body.children) if frag.body else list(frag.children)
        # `insert_before(n)` always puts n immediately before target, so if we
        # want the original order preserved we must insert in reverse — same
        # logic as insert_after.
        for n in reversed(nodes):
            target.insert_before(n)
    elif ch.op == "remove":
        target.decompose()


def _root(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/"
