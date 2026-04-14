"""Regression: LLM-output coercion for the `source` and `op` literals, and
graceful drop of malformed changes instead of crashing the whole plan."""
from app.agents.strategist import _coerce_change, _coerce_op, _coerce_source, _valid_change
from app.schemas import Change


def test_source_comma_list_collapses_to_ad():
    assert _coerce_source("ad.offer, ad.value_prop") == "ad"


def test_source_page_precedence_when_no_ad():
    assert _coerce_source("page copy inventory entry") == "page"


def test_source_falls_back_to_cro_principle():
    assert _coerce_source("marketing best practice") == "cro_principle"


def test_op_invalid_falls_back_to_replace_text():
    assert _coerce_op("REPLACE-SECTION") == "replace_text"  # hyphen, case
    assert _coerce_op("replace_section") == "replace_section"


def test_valid_change_rejects_malformed():
    assert not _valid_change({"op": "replace_text"})       # no selector
    assert not _valid_change({"selector": "x"})            # no payload
    assert _valid_change({"selector": "x", "payload": "y"})


def test_coerced_change_builds_pydantic_model():
    c = Change(**_coerce_change({
        "selector": "[data-troopod-id='t1']",
        "op": "replace_section",
        "payload": "<h1>Hi</h1>",
        # Malformed source — LLM dumped the field path.
        "source": "ad.offer, ad.cta_text",
        "rationale": "match ad",
    }))
    assert c.source == "ad"
    assert c.op == "replace_section"
