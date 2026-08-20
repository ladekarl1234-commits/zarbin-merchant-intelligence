"""Control Center API: platform, product performance, AI-ops, sources, AI-eval, feedback."""
from fastapi.testclient import TestClient

from zarin.api import app

client = TestClient(app)


def _a_merchant() -> str:
    return client.get("/api/meta").json()["merchants"][0]["merchant_key"]


def test_admin_platform():
    r = client.get("/api/admin/platform")
    assert r.status_code == 200
    d = r.json()
    assert d["kpis"]["total_merchants"] >= 2
    assert d["kpis"]["sessions"] > 0 and "insights" in d and "categories" in d


def test_admin_performance_records_requests():
    client.get("/api/meta")            # generate at least one API hit
    client.get("/api/admin/platform")
    d = client.get("/api/admin/performance").json()
    assert d["has_data"] and d["total"] >= 1
    assert d["latency_ms"]["p95"] is not None
    assert any(e["path"] == "/api/admin/platform" for e in d["endpoints"])


def test_copilot_returns_contract_offline():
    m = _a_merchant()
    d = client.get("/api/copilot", params={"m": m, "q": "چرا فروشم کم شد؟"}).json()
    # offline (no key in test env) → deterministic, grounded, never a fallback-from-error
    assert d["source"] == "deterministic" and d["grounded"] is True and d["fallback"] is False
    assert d["confidence"] in ("high", "medium", "low") and "evidence" in d


def test_copilot_feedback_and_ai_ops():
    m = _a_merchant()
    d = client.get("/api/copilot", params={"m": m, "q": "این هفته روی چی تمرکز کنم؟"}).json()
    fb = client.post("/api/copilot/feedback", params={"m": m, "intent": d["intent"], "useful": True})
    assert fb.status_code == 200 and fb.json()["ok"]
    ops = client.get("/api/admin/ai-ops").json()
    assert ops["total"] >= 1 and "grounded_rate" in ops
    assert ops["feedback"]["total"] >= 1 and ops["feedback"]["useful"] >= 1


def test_admin_sources_ga4_unconfigured():
    d = client.get("/api/admin/sources").json()
    by = {s["id"]: s for s in d["sources"]}
    assert by["zarinpal"]["status"] == "ok" and by["zarinpal"]["is_truth"]
    assert by["ga4"]["status"] == "not_configured" and not by["ga4"]["connected"]
    assert d["cross_source_insights"] == []   # honest: nothing until GA4 is connected


def test_admin_ai_eval_reports_separate_dimensions():
    d = client.get("/api/admin/ai-eval").json()
    ind = d["indicators"]
    assert ind["deterministic_correctness"] == 1.0        # routing is dataset-independent
    assert ind["grounding_quality"] is not None
    assert ind["language_quality"] is None and ind["business_usefulness"] is None  # not auto-scored


def test_admin_platform_rejects_bad_date():
    assert client.get("/api/admin/platform", params={"f": "not-a-date"}).status_code == 400


def test_ops_copilot_is_grounded_and_scoped_to_platform():
    d = client.get("/api/admin/copilot", params={"q": "وضعیت کل سیستم چطوره؟"}).json()
    assert d["source"] == "deterministic" and d["grounded"] and d["intent"] == "system"
    assert len(d["evidence"]) >= 1
    # ops copilot must not require or leak a merchant scope; it answers platform-level
    d2 = client.get("/api/admin/copilot", params={"q": "کدام منبع sync نشده؟"}).json()
    assert d2["intent"] == "sources" and "زرین‌پال" in d2["answer_fa"]


def test_ops_copilot_feedback():
    d = client.get("/api/admin/copilot", params={"q": "AI امروز چطور عمل کرده؟"}).json()
    fb = client.post("/api/admin/copilot/feedback", params={"intent": d["intent"], "useful": False})
    assert fb.status_code == 200 and fb.json()["ok"]
