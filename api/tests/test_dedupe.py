"""Regression: repeated-phrase detection — animation-layer text triplication
used by modern hero sections (Linear, Framer, Apple) gets collapsed to a
single clean phrase."""
from app.tools.scrape import _dedupe_repeated


def test_triple_repeat_collapses():
    src = ("The product development system for teams and agents "
           "The product development system for teams and agents "
           "The product development system for teams and agents")
    out = _dedupe_repeated(src)
    assert out == "The product development system for teams and agents"


def test_double_repeat_collapses():
    src = "Plan, build, ship. Plan, build, ship."
    assert _dedupe_repeated(src) == "Plan, build, ship."


def test_non_repeat_kept_verbatim():
    src = "The product development system for teams and agents"
    assert _dedupe_repeated(src) == src


def test_short_string_untouched():
    # Too short for the heuristic to lie about it.
    assert _dedupe_repeated("Hi Hi") == "Hi Hi"


def test_whitespace_normalized():
    src = "  Hello   world   Hello   world  "
    assert _dedupe_repeated(src) == "Hello world"
