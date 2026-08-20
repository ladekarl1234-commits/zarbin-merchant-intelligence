"""AI layer: free-model policy, evidence-safe context, grounded gateway, telemetry.

These encode the non-negotiable safety rules: the model never sees raw data, never
picks a paid model, and can never change a number the deterministic engine computed.
"""
import json

import pytest

from zarin import copilot
from zarin.ai import gateway, models, telemetry
from zarin.ai import safe_context as sc
from zarin.ai.provider import Completion

DET = "فروش موفق ۶۱٬۸۰۰٬۰۰۰٬۰۰۰ ریال از ۱۲۳ پرداخت بود"


class FakeProvider:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def complete(self, system, user, *, max_tokens=600):
        return Completion(text=self.text, provider="fake", model="fake/model:free",
                          prompt_tokens=10, completion_tokens=5, total_tokens=15,
                          cost_usd=0.0, latency_ms=3)


class BoomProvider:
    name = "boom"

    def complete(self, system, user, *, max_tokens=600):
        raise RuntimeError("network down")


def test_free_model_policy_rejects_paid_and_auto():
    assert models.is_free("meta-llama/llama-3.3-70b-instruct:free")
    assert not models.is_free("openai/gpt-4o")
    assert not models.is_free("openrouter/auto")   # bills at selected rate — must be rejected
    assert not models.is_free("")
    used, reason = models.enforce_free("openai/gpt-4o")
    assert used == models.DEFAULT_FREE_MODEL and models.is_free(used) and reason
    ok, reason2 = models.enforce_free("x/y:free")
    assert ok == "x/y:free" and reason2 is None


def test_safe_context_never_leaks_raw_data():
    ev = {"metric_id": "gmv", "name_fa": "فروش", "definition_fa": "d", "formula": "f",
          "grain": "session", "caveats": ["c"], "sql": "SELECT amount FROM sessions",
          "params": {"payer_card_key": "CARD-SECRET-123", "m": "M1"}, "n": 10, "period": "p"}
    ctx = sc.build(question="q", merchant_scope="M1", intent="i",
                   deterministic_answer_fa="A", evidence=[ev])
    blob = json.dumps(ctx, ensure_ascii=False)
    for banned in ("CARD-SECRET-123", "payer_card_key", "SELECT", "params"):
        assert banned not in blob
    assert ctx["metrics"][0]["name"] == "فروش"  # safe fields survive


def test_safe_context_assert_blocks_banned_keys_at_any_depth():
    with pytest.raises(ValueError):
        sc.assert_safe({"a": [{"nested": {"sql_text": "x"}}]})
    with pytest.raises(ValueError):
        sc.assert_safe({"query_params": {"session_id": 1}})


def test_gateway_uses_llm_when_grounded():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=FakeProvider("حدود ۶۱٫۸ میلیارد ریال از ۱۲۳ پرداخت داشتی"))
    assert r.source == "llm" and r.grounded and not r.fallback
    assert r.cost_usd == 0.0 and r.total_tokens == 15


def test_gateway_rejects_hallucinated_number():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=FakeProvider("فروش تو ۹۹۹۹ ریال و ۴۵۶ مشتری بود"))
    assert r.fallback and r.answer_fa == DET          # the truth is preserved
    assert r.grounded and "hallucination_risk" in r.quality_flags


def test_gateway_provider_error_falls_back():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=BoomProvider())
    assert r.fallback and r.answer_fa == DET and "provider_error" in r.quality_flags


def test_gateway_offline_returns_deterministic():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=None, _use_default=False)
    assert r.source == "deterministic" and not r.fallback and r.grounded


def test_telemetry_summary_reflects_events():
    telemetry.reset()
    gateway.explain(question="q", merchant_scope="M1", intent="overview",
                    deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                    provider=FakeProvider("۶۱٫۸ میلیارد ریال"))
    s = telemetry.summary()
    assert s["has_data"] and s["total"] == 1 and s["llm_requests"] == 1
    assert s["grounded_rate"] == 1.0 and s["cost_usd_total"] == 0.0


def test_copilot_answer_numbers_are_deterministic_even_with_bad_llm():
    """AI cannot change a metric value: a lying provider is discarded, numbers stay the engine's."""
    telemetry.reset()
    d = copilot.answer("M1", "چرا فروشم کم شد؟", "2026-01-01", "2026-02-28",
                       provider=FakeProvider("فروش ۸۸۸۸۸۸ و رشد ۷۷۷٪ داشتی"))
    assert d["fallback"] and "hallucination_risk" in d["quality_flags"]
    assert "۸۸۸۸۸۸" not in d["answer_fa"] and "۷۷۷" not in d["answer_fa"]
