"""Suppression, opportunity math, and API smoke tests."""
from fastapi.testclient import TestClient

from zarin.analytics import period_agg
from zarin.api import app
from zarin.insights import _gap_card, generate
from zarin.peers import benchmarks

client = TestClient(app)
JAN = ("2026-01-01", "2026-01-31")


def test_small_peer_pool_suppresses_benchmarks():
    """Fixture merchants are below the 500-session pool floor → no fabricated percentiles."""
    b = benchmarks("M1", *JAN)
    assert not b["group"]["sufficient"]
    assert all(r["suppressed"] for r in b["rows"])
    assert all("percentile" not in r for r in b["rows"])


def test_insights_restraint_on_small_samples():
    """1 paid-unverified session (<5) and <100 sessions → no friction/opportunity cards."""
    cards = generate("M1", *JAN)
    assert [c for c in cards if c["kind"] in ("no_attempt_gap", "inbank_gap", "paid_unverified")] == []


def test_opportunity_is_not_naive_failed_sum():
    """Opportunity must be gap-based, far below the naive 'sum of failed amounts'."""
    me = period_agg("M1", *JAN)
    me["m"] = "M1"
    peers = [{"no_attempt_rate": r} for r in (0.01, 0.02, 0.03, 0.04, 0.05)]
    me["no_attempt_rate"] = 0.30  # pretend a large gap
    me["sessions"] = 1000
    card = _gap_card(kind="no_attempt_gap", me=me, peers_rates=peers, rate_key="no_attempt_rate",
                     f=JAN[0], t=JAN[1], title_fa="x", diagnosis_fa="x", action_fa="x",
                     effort="medium", metric_id="no_attempt_rate")
    assert card is not None
    # naive failed sum in fixture Jan = 999999+70000+80000 = 1,149,999 for only 7 sessions;
    # gap math: (0.30-0.03)×1000 sessions × conv(attempted)=0.5 × ticket 200000 = 27M — but the
    # invariant we assert is structural: impact uses the gap, not the failed amounts.
    gap_mid = 0.30 - 0.03
    conv_attempted = me["verified"] / me["attempted"]
    expected = gap_mid * 1000 * conv_attempted * 200000  # median verified ticket of M1 = 200000
    assert abs(card["impact_low"] - round(expected)) <= 1
    assert card["impact_high"] >= card["impact_low"]


def test_gap_below_2pp_yields_no_card():
    me = period_agg("M1", *JAN)
    me["m"] = "M1"
    me["sessions"] = 1000
    me["no_attempt_rate"] = 0.05
    peers = [{"no_attempt_rate": r} for r in (0.04, 0.045, 0.05, 0.055, 0.06)]
    assert _gap_card(kind="no_attempt_gap", me=me, peers_rates=peers, rate_key="no_attempt_rate",
                     f=JAN[0], t=JAN[1], title_fa="x", diagnosis_fa="x", action_fa="x",
                     effort="medium", metric_id="no_attempt_rate") is None


def test_api_smoke():
    assert client.get("/api/meta").status_code == 200
    ov = client.get("/api/overview", params={"m": "M1", "f": JAN[0], "t": JAN[1]}).json()
    assert ov["kpis"]["gmv"] == 600000
    assert ov["kpis"]["paid_unverified_amount"] == 50000
    fu = client.get("/api/funnel", params={"m": "M1", "f": JAN[0], "t": JAN[1]}).json()
    assert fu["outcomes"]["no_attempt"] == 1
    assert client.get("/api/overview", params={"m": "NOPE"}).status_code == 404
    cp = client.get("/api/copilot", params={"m": "M1", "q": "تلاش مجدد چقدر برگرداند؟"}).json()
    assert "نجات" in cp["answer_fa"] or "تلاش" in cp["answer_fa"]
    ev = client.get("/api/evidence/sessions", params={"m": "M1", "outcome": "verified"}).json()
    assert ev["total"] == 4 and len(ev["rows"]) == 4


def test_fee_never_presented_as_real_fee():
    meta = client.get("/api/meta").json()
    assert "کارمزد واقعی زرین‌پال نیست" in meta["notes"]["fee"]
    from zarin.registry import REGISTRY
    assert "نسبی" in REGISTRY["fee_index"].name_fa
