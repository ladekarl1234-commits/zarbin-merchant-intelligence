"""ZB-044: ops_copilot._plan's 8 first-match-wins regexes were 54% covered — only `system`
and `sources`, plus one loose `ai_*` probe, ever ran. A parametrized routing table over all 9
intents, plus the two adversarial phrasings named in the finding (a model question that is
really a latency question; a bare 'cost' question that must NOT default to AI spend), and a
check that no branch invents a number when its underlying telemetry is empty.
"""
import re
from unittest import mock

import pytest

from zarin import control, ops_copilot

PERIOD = ("2026-01-01", "2026-06-30")

# one representative Persian question per intent — the routing table the finding says never
# existed. Each must land on the intent it names, first-match-wins regex ordering and all.
ROUTING_TABLE = [
    ("وضعیت کل سیستم چطوره؟", "system"),
    ("AI امروز چطور عمل کرده؟", "ai_health"),
    ("چند درصد پاسخ‌ها مستند بوده‌اند؟", "ai_grounded"),
    ("چرا نرخ fallback بالا رفته؟", "ai_fallback"),
    ("چه مدلی بیشتر استفاده شده؟", "ai_model"),
    ("هزینه هوش مصنوعی چقدر شده؟", "ai_cost"),
    ("چرا سرعت سایت کند شده؟", "perf"),
    ("کدام منبع sync نشده؟", "sources"),
    ("چه چیزی الان نیاز به توجه دارد؟", "attention"),
]


@pytest.mark.parametrize("question,expected_intent", ROUTING_TABLE)
def test_routes_each_intent_correctly(question, expected_intent):
    _, intent, _, _ = ops_copilot._plan(question, *PERIOD)
    assert intent == expected_intent


def test_model_latency_question_routes_to_perf_not_ai_model():
    """«کدام مدل کند است؟» names a model AND asks about speed — the more specific perf intent
    must win, not the bare model-usage intent (the model regex has an explicit NOT-speed guard
    for exactly this compound phrasing)."""
    _, intent, _, _ = ops_copilot._plan("کدام مدل کند است؟", *PERIOD)
    assert intent == "perf"
    assert intent != "ai_model"


def test_generic_cost_question_does_not_default_to_ai_cost():
    """«هزینه پذیرندگان چقدر است؟» mentions cost but has no AI/model/token qualifier — the
    cost regex was anchored (ZB-044) specifically so a merchant-side cost question can never
    be misrouted into the AI-spend answer."""
    _, intent, _, _ = ops_copilot._plan("هزینه پذیرندگان چقدر است؟", *PERIOD)
    assert intent != "ai_cost"


def test_compound_question_prefers_the_more_specific_grounded_intent_over_cost():
    """«چند درصد پاسخ ها مستند بوده و هزینه چقدر شده؟» mentions cost but — again — with no
    AI/model qualifier attached to «هزینه», so it must not swallow the (correctly answerable)
    grounded-rate question into a cost answer."""
    _, intent, _, _ = ops_copilot._plan("چند درصد پاسخ ها مستند بوده و هزینه چقدر شده؟", *PERIOD)
    assert intent == "ai_grounded"


_HAS_DIGIT = re.compile(r"[0-9۰-۹]")


@pytest.mark.parametrize("question,patch_fn,attr", [
    ("AI امروز چطور عمل کرده؟", lambda: {"has_data": False}, "ai_ops"),
    ("چند درصد پاسخ‌ها مستند بوده‌اند؟", lambda: {"has_data": False}, "ai_ops"),
    ("چرا نرخ fallback بالا رفته؟", lambda: {"has_data": False}, "ai_ops"),
    ("چه مدلی بیشتر استفاده شده؟", lambda: {"has_data": False, "models": []}, "ai_ops"),
    ("هزینه هوش مصنوعی چقدر شده؟", lambda: {"has_data": False}, "ai_ops"),
    ("چرا سرعت سایت کند شده؟", lambda: {"has_data": False}, "performance"),
])
def test_honest_no_data_answer_never_fabricates_a_number(monkeypatch, question, patch_fn, attr):
    """When the backing telemetry function reports has_data=False, the answer text must be an
    honest 'no data yet' sentence — never a number interpolated from missing/zeroed data."""
    monkeypatch.setattr(control, attr, patch_fn)
    text, _intent, refs, conf = ops_copilot._plan(question, *PERIOD)
    assert not _HAS_DIGIT.search(text), f"answer fabricated a number with no telemetry: {text!r}"
    assert refs == []
    assert conf in ("low", "medium")


def test_attention_with_no_signals_is_honest_not_empty_evidence():
    """With no performance/platform signals, `attention` must say nothing needs attention
    rather than silently returning an empty answer."""
    with mock.patch.object(control, "performance", lambda: {"has_data": False}), \
         mock.patch.object(control, "platform", lambda f, t: {"insights": []}):
        text, intent, _refs, _conf = ops_copilot._plan("چه چیزی الان نیاز به توجه دارد؟", *PERIOD)
    assert intent == "attention"
    assert "شناسایی نشده" in text or "موردی" in text
