"""Load Design.md files as system prompts. Keeps agent behavior and docs in lockstep."""
from functools import lru_cache
from pathlib import Path

_DESIGN = Path(__file__).resolve().parents[3] / "docs" / "design"


@lru_cache
def load(name: str) -> str:
    p = _DESIGN / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


EXTRACTOR = load("01_extractor.md")
STRATEGIST = load("02_strategist.md")
BUILDER = load("03_builder.md")
VERIFIER = load("04_verifier.md")
CRITIC = load("06_critic.md")
