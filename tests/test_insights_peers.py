"""Suppression, opportunity math, and API smoke tests."""
from fastapi.testclient import TestClient

from zarin.analytics import period_agg
from zarin.api import app
from zarin.insights import _apply_gmv_cap, _Ctx, _gap_card, _period_tickets, format_impact, generate
from zarin.peers import benchmarks

client = TestClient(app)
JAN = ("2026-01-01", "2026-01-31")


def _ctx(*, sessions=1000, na_rate=0.30, gmv=None, peers=(0.01, 0.02, 0.03, 0.04, 0.05)):
    """Build the generator context the cards take, with the fixture's real tickets."""
    me = period_agg("M1", *JAN)
    me["m"] = "M1"
    me["sessions"] = sessions
    me["no_attempt_rate"] = na_rate
    if gmv is not None:
        me["gmv"] = gmv
    return _Ctx(m="M1", f=JAN[0], t=JAN[1], me=me, g={"sufficient": True, "peers": []},
                peers_rates=[{"no_attempt_rate": r} for r in peers],
                tickets=_period_tickets("M1", *JAN))


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


def test_opportunity_is_gap_based_with_honest_band():
    """Opportunity = gap × sessions × [0.5..1.0] × ticket, NOT the sum of failed amounts,
    and the interval spans a real recovery-fraction band (high ≈ 2× low)."""
    ctx = _ctx(gmv=10_000_000_000)  # large, so the realized-GMV cap does not fire here
    card = _gap_card(ctx, kind="no_attempt_gap", rate_key="no_attempt_rate",
                     title_fa="x", diagnosis_fa="x", action_fa="x",
                     effort="medium", metric_id="no_attempt_rate")
    assert card is not None
    _apply_gmv_cap([card], ctx.me["gmv"])
    assert not card["capped"]
    assert 0 < card["impact_low"] < card["impact_high"]
    # recovery-fraction band: high uses 1.0, low uses 0.5 → ratio 2.0
    assert abs(card["impact_high"] / card["impact_low"] - 2.0) < 1e-6
    # the opportunity evidence carries the real formula, not an empty string
    opp = next(e for e in card["evidence"] if e["metric_id"] == "opportunity")
    assert "recoverable" in opp["sql"] and opp["params"]["recovery_fraction_high"] == 1.0
    # few peers → confidence capped at 'low', never 'high'
    assert card["confidence"] == "low" and card["n_peers"] == 5


def test_opportunity_capped_at_realized_gmv():
    """An estimate larger than the merchant's whole realized GMV is capped and flagged —
    it is a broken-funnel signal, not a recoverable number."""
    ctx = _ctx()  # real M1 Jan GMV is only 600,000
    card = _gap_card(ctx, kind="no_attempt_gap", rate_key="no_attempt_rate",
                     title_fa="x", diagnosis_fa="x", action_fa="x",
                     effort="medium", metric_id="no_attempt_rate")
    assert card is not None
    _apply_gmv_cap([card], ctx.me["gmv"])
    assert card["capped"] and card["impact_high"] <= ctx.me["gmv"]


def test_cap_covers_every_estimate_generator_not_just_the_peer_gap():
    """The cap used to live inside one generator, so other kinds published estimates larger than
    the merchant's entire realized GMV (ZB-006). The shared guard must clamp any rial estimate,
    while leaving realized sums and count-denominated cards alone."""
    gmv = 1_000_000
    cards = [
        {"kind": "high_value_friction", "card_type": "opportunity", "impact_low": 5_000_000,
         "impact_high": 9_000_000, "impact_label_fa": "x"},
        {"kind": "repeat_gap", "card_type": "opportunity", "impact_low": 1, "impact_high": 2_000_000,
         "impact_mid": 1_500_000, "impact_label_fa": "x"},
        {"kind": "paid_unverified", "card_type": "opportunity", "impact_low": 8_000_000,
         "impact_high": 8_000_000, "impact_is_realized": True, "impact_label_fa": "x"},
        {"kind": "psp_friction", "card_type": "opportunity", "impact_low": 10, "impact_high": 900,
         "impact_is_count": True, "impact_label_fa": "x"},
    ]
    _apply_gmv_cap(cards, gmv)
    by = {c["kind"]: c for c in cards}
    assert by["high_value_friction"]["impact_high"] == gmv and by["high_value_friction"]["capped"]
    assert by["repeat_gap"]["impact_high"] == gmv and by["repeat_gap"]["impact_mid"] <= gmv
    assert by["paid_unverified"]["impact_high"] == 8_000_000 and not by["paid_unverified"]["capped"]
    assert by["psp_friction"]["impact_high"] == 900 and not by["psp_friction"]["capped"]


def test_zero_gmv_merchant_cannot_publish_a_rial_opportunity():
    """The extreme of ZB-006: with NO realized sales there is no demonstrated ability to convert,
    so a peer-gap rial estimate is unsupportable. The first fix early-returned on gmv<=0, which
    let those cards through completely UNCAPPED — worse than the original bug."""
    cards = [{"kind": "no_attempt_gap", "card_type": "opportunity", "impact_low": 20_000_000_000,
              "impact_mid": 30_000_000_000, "impact_high": 40_000_000_000, "impact_label_fa": "x"}]
    _apply_gmv_cap(cards, 0)
    c = cards[0]
    assert c["impact_high"] == 0 and c["impact_low"] == 0
    assert c["card_type"] == "alert" and c["capped"] is True


def test_no_merchant_anywhere_publishes_an_opportunity_above_its_realized_gmv():
    """End-to-end guard over every fixture merchant — the unit test above pins the helper, this
    pins what `generate()` actually ships, which is where ZB-006 escaped."""
    from zarin.analytics import period_agg
    from zarin.db import q
    period = ("2026-01-01", "2026-06-30")
    for row in q("SELECT merchant_key FROM merchant_stats"):
        m = row["merchant_key"]
        gmv = period_agg(m, *period)["gmv"] or 0
        for c in generate(m, *period):
            if c.get("impact_is_count") or c.get("impact_is_realized") or c["card_type"] != "opportunity":
                continue
            assert (c.get("impact_high") or 0) <= gmv, f"{m}/{c['kind']} exceeds realized GMV {gmv}"


def test_format_impact_never_prints_a_count_as_rial():
    """The copilot used to render transaction counts with a rial formatter (ZB-013)."""
    count_card = {"impact_low": 10, "impact_high": 900, "impact_is_count": True, "impact_label_fa": "x"}
    money_card = {"impact_low": 5_000_000, "impact_high": 9_000_000, "impact_label_fa": "x"}
    assert "تراکنش" in format_impact(count_card) and "ریال" not in format_impact(count_card)
    assert "ریال" in format_impact(money_card)


def test_gap_below_2pp_yields_no_card():
    ctx = _ctx(na_rate=0.05, peers=(0.04, 0.045, 0.05, 0.055, 0.06))
    assert _gap_card(ctx, kind="no_attempt_gap", rate_key="no_attempt_rate",
                     title_fa="x", diagnosis_fa="x", action_fa="x",
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
