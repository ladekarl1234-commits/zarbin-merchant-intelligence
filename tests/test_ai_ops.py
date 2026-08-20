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


def test_free_model_policy_rejects_paid_models():
    assert ai_ops._free_model_policy("openrouter/free") == "openrouter/free"
    assert ai_ops._free_model_policy("some/model:free") == "some/model:free"
    assert ai_ops._free_model_policy("some/paid-model") == "openrouter/free"


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


def test_admin_copilot_is_grounded_without_external_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ai_ops, "AI_EVENTS_PATH", tmp_path / "events.jsonl")
    ops = {
        "ai": {"fallback_rate": 0.12, "p95_latency_ms": 420, "cost_usd": 0.0, "grounded_rate": 0.99,
               "requests": 10, "avg_latency_ms": 200, "models": {"zarbin-rules": 10}, "intents": {}},
        "api": {"p95_latency_ms": 90, "error_rate": 0.0},
        "sources": [{"label": "Google Analytics 4", "configured": False}],
        "platform": {"merchants": 3, "sessions": 100},
        "slo": {"target_ai_fallback_rate": 0.05},
    }
    r = ai_ops.admin_answer("fallback چقدر است؟", ops)
    assert r["intent"] == "ai_fallback"
    assert r["ai"]["grounded"] is True
    assert r["ai"]["mode"] == "deterministic"
    assert (tmp_path / "events.jsonl").exists()


def test_ga4_snapshot_becomes_insight_not_just_display(monkeypatch, tmp_path):
    p = tmp_path / "ga4.json"
    rows = []
    for i in range(7):
        rows.append({"date": f"202608{1+i:02d}", "sessions": 100, "users": 80, "events": 300, "purchase_revenue": 10})
    for i in range(7):
        rows.append({"date": f"202608{8+i:02d}", "sessions": 140, "users": 100, "events": 360, "purchase_revenue": 12})
    p.write_text(json.dumps({"rows": rows, "totals": {}, "period": {"from": "2026-08-01", "to": "2026-08-14"}}), encoding="utf-8")
    monkeypatch.setattr(connectors, "GA4_SNAPSHOT", p)
    cards = connectors.ga4_insights()
    traffic = next(c for c in cards if c["metric"] == "sessions")
    assert abs(traffic["change"] - 0.4) < 1e-12
    assert traffic["sample_days"] == 14
    assert "علت" in traffic["caveat_fa"]
