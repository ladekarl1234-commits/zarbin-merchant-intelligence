import json

from zarin import ai_ops, connectors


def test_safe_evidence_strips_raw_query_parameters():
    base = {
        "evidence": [{
            "metric_id": "x",
            "name_fa": "نمونه",
            "definition_fa": "تعریف",
            "formula": "a/b",
            "n": 10,
            "period": "2026-01",
            "caveats": ["c"],
            "method_fa": "روش",
            "sql": "SELECT payer_card_key FROM raw",
            "params": {"merchant": "M1", "secret": "x"},
        }]
    }
    safe = ai_ops._safe_evidence(base)
    assert len(safe) == 1
    assert "sql" not in safe[0]
    assert "params" not in safe[0]
    assert safe[0]["metric_id"] == "x"


def test_ai_stats_empty_and_config_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_ops, "AI_EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    s = ai_ops.stats()
    assert s["requests"] == 0
    assert s["openrouter_configured"] is False
    assert s["default_model"]


def test_ai_stats_aggregates_grounding_fallback_and_latency(monkeypatch, tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join([
        json.dumps({"model": "a", "intent": "x", "latency_ms": 100, "success": True, "grounded": True, "fallback": False, "cost_usd": 0}),
        json.dumps({"model": "a", "intent": "y", "latency_ms": 300, "success": True, "grounded": False, "fallback": True, "cost_usd": 0}),
    ]), encoding="utf-8")
    monkeypatch.setattr(ai_ops, "AI_EVENTS_PATH", p)
    s = ai_ops.stats()
    assert s["requests"] == 2
    assert s["grounded_rate"] == 0.5
    assert s["fallback_rate"] == 0.5
    assert s["avg_latency_ms"] == 200
    assert s["models"] == {"a": 2}


def test_ga4_unconfigured_is_explicit(monkeypatch, tmp_path):
    monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(connectors, "GA4_SNAPSHOT", tmp_path / "missing.json")
    s = connectors.ga4_status()
    assert not s.configured
    assert s.state == "not_configured"
