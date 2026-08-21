"""ZB-042: six of nine card generators (recovery_gap, high_value_friction, repeat_gap,
concentration, psp_friction, and — per the audit's correction — paid_unverified) never ran in
the old suite, which only exercised `_gap_card` directly with synthetic input below
MIN_SESSIONS_INSIGHT. These tests use the larger merchants built in conftest.py
(MPSP/MHVF/MBROKEN/MHEALTHY) to run the real generators end to end through `generate()`.
"""
from tests.conftest import BROKEN_PERIOD, MHVF_PERIOD, MPSP_PERIOD
from zarin.insights import generate


def _by_kind(cards):
    return {c["kind"]: c for c in cards}


def test_psp_friction_excludes_degenerate_rail_and_needs_tercile_support():
    """MPSP has PSP-A (80% first-try), PSP-B (30%), and a degenerate PSP-C (~1.7%, the
    ZB-016 selection-bias guard target). The card must name A as best / B as worst and must
    NEVER mention PSP-C — including it would manufacture a phantom opportunity from a rail
    that is disabled, not merely weak."""
    cards = _by_kind(generate("MPSP", *MPSP_PERIOD))
    card = cards.get("psp_friction")
    assert card is not None, "psp_friction should fire: PSP-A/B have a 50pp gap holding in 3/3 amount terciles"
    assert "PSP-C" not in card["title_fa"]
    assert "PSP-C" not in card["observation_fa"]
    assert "PSP-C" not in card["diagnosis_fa"]
    assert card["title_fa"].count("PSP-B") >= 1 or "PSP-B" in card["observation_fa"]
    # evidence params must record which two PSPs and how many of the 3 amount terciles held
    ev = next(e for e in card["evidence"] if e["metric_id"] == "first_try_conv")
    assert ev["params"]["worst_psp"] == "PSP-B"
    assert ev["params"]["best_psp"] == "PSP-A"
    assert ev["params"]["amount_terciles_holding"] >= 2


def test_paid_unverified_names_the_callback_failure_for_automated_merchant():
    """ZB-028: the fixture's verify_type is 'Automated' (conftest default), so the diagnosis
    must point at the failing verify/callback — never at the old wrong advice to 'enable
    auto-verify' (that's only correct advice for a manually-verified merchant)."""
    cards = _by_kind(generate("MPSP", *MPSP_PERIOD))
    card = cards.get("paid_unverified")
    assert card is not None
    assert "فراخوانی تایید" in card["diagnosis_fa"] or "callback" in card["diagnosis_fa"].lower()
    assert "تایید خودکار تراکنش‌ها را فعال کنید" not in card["diagnosis_fa"]
    assert "تایید خودکار تراکنش‌ها را فعال کنید" not in card["action_fa"]


def test_high_value_friction_fires_on_the_amount_tied_fixture():
    """MHVF: 400 sessions tied at 50,000 rial (90% conv), 100 tied at 900,000 rial (40% conv,
    exactly the top ntile(5) quintile). gap = 0.90-0.40 = 0.50 > the 0.05 threshold."""
    cards = _by_kind(generate("MHVF", *MHVF_PERIOD))
    card = cards.get("high_value_friction")
    assert card is not None
    assert card["impact_high"] > 0
    assert card["n"] == 100


def test_high_value_friction_is_deterministic_across_repeated_calls():
    """ZB-120 regression: ntile(5) OVER (ORDER BY amount) with no tiebreaker let tied amounts
    (constant in this fixture, as in real payments data) land in different quintiles on
    different runs, so impact_high changed call to call. With the (amount, session_key)
    tiebreaker in place, two consecutive generate() calls must return byte-identical
    impact_low/impact_high for EVERY card, not just high_value_friction."""
    runs = [generate("MHVF", *MHVF_PERIOD) for _ in range(5)]
    baseline = [(c["kind"], c["impact_low"], c["impact_high"]) for c in runs[0]]
    for cards in runs[1:]:
        assert [(c["kind"], c["impact_low"], c["impact_high"]) for c in cards] == baseline


def test_absolute_funnel_fires_for_broken_merchant_with_no_peer_group():
    """MBROKEN is alone in its category (no peer group can form) with na_rate=75%, conv=25%
    and 60 sessions (>= MIN_SIGNAL_SESSIONS, < MIN_SESSIONS_INSIGHT so peer-gap cards are
    gated off too) — the absolute-funnel fallback is the ONLY thing that can tell this
    merchant its funnel is broken (ZB-003)."""
    cards = generate("MBROKEN", *BROKEN_PERIOD)
    kinds = [c["kind"] for c in cards]
    assert "absolute_funnel" in kinds
    card = _by_kind(cards)["absolute_funnel"]
    assert card["card_type"] == "alert"


def test_absolute_funnel_does_not_fire_for_a_healthy_merchant():
    """MHEALTHY (same shape, alone in its own category) has na_rate=5%, conv=85% — no card,
    peer-based or absolute, should claim its funnel is broken."""
    cards = generate("MHEALTHY", *BROKEN_PERIOD)
    kinds = [c["kind"] for c in cards]
    assert "absolute_funnel" not in kinds


def test_ranking_orders_opportunities_before_alerts_and_by_descending_score(monkeypatch):
    """Unit-tests the ranking/sort step in generate() directly against controlled canned cards
    (rather than hoping a real fixture happens to produce exactly one alert and N opportunities),
    so the assertion is about the sort key, not about fixture engineering:
      1. opportunities must ALWAYS sort before alerts, regardless of the alert's risk_gmv;
      2. within opportunities, `score` must be strictly descending.
    """
    from zarin import insights as ins

    def gen_alert(ctx):
        return {"id": "z_alert", "kind": "z_alert", "card_type": "alert",
                "risk_gmv": 999_999_999_999, "impact_low": 0, "impact_high": 0}

    def gen_opp_low(ctx):
        return {"id": "a_opp_low", "kind": "a_opp_low", "card_type": "opportunity",
                "impact_low": 1_000, "impact_high": 2_000, "confidence": "low", "effort": "hard"}

    def gen_opp_high(ctx):
        return {"id": "b_opp_high", "kind": "b_opp_high", "card_type": "opportunity",
                "impact_low": 500_000, "impact_high": 1_000_000, "confidence": "high", "effort": "easy"}

    monkeypatch.setattr(ins, "_GENERATORS", (gen_alert, gen_opp_low, gen_opp_high))
    cards = ins.generate("MPSP", *MPSP_PERIOD)
    kinds = [c["kind"] for c in cards]
    assert kinds.index("z_alert") > kinds.index("a_opp_low")
    assert kinds.index("z_alert") > kinds.index("b_opp_high")
    opp_scores = [c["score"] for c in cards if c["card_type"] == "opportunity"]
    assert opp_scores == sorted(opp_scores, reverse=True)
    assert opp_scores[0] > 0
