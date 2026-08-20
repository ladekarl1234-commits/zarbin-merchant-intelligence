"""Metric-correctness tests for the dangerous mistakes named in the spec."""
from zarin.analytics import changes, customers, funnel, period_agg
from zarin.db import q1

JAN = ("2026-01-01", "2026-01-31")
ALL = ("2026-01-01", "2026-02-28")


def test_attempts_are_not_sessions():
    """9 attempt rows for M1 must collapse to 7 sessions."""
    assert q1("SELECT count(*) AS n FROM sessions WHERE merchant_key='M1'")["n"] == 8  # 7 Jan + 1 Feb
    assert q1("SELECT count(*) AS n FROM attempts WHERE merchant_key='M1'")["n"] == 9  # try_seq>0 rows


def test_retries_do_not_inflate_gmv_or_counts():
    a = period_agg("M1", *JAN)
    # S1 (3 tries, 100k) + S6 (200k) + S7 (300k) — each counted once
    assert a["verified"] == 3
    assert a["gmv"] == 600000


def test_noattempt_is_not_a_bank_failure():
    a = period_agg("M1", *JAN)
    assert a["no_attempt"] == 1
    assert a["failed_bank"] == 1        # S5 only
    assert a["abandoned_inbank"] == 1   # S4 only


def test_paid_is_not_verified():
    a = period_agg("M1", *JAN)
    assert a["paid_unverified"] == 1
    assert a["paid_unverified_amount"] == 50000
    assert a["conv"] == 3 / 7           # Paid session is NOT counted as success


def test_first_try_and_recovery():
    a = period_agg("M1", *JAN)
    assert a["first_try_ok"] == 3        # S6, S7, S3 (Paid first try is not a failed attempt)
    assert a["first_try_verified"] == 2  # S6, S7 — the user-facing first-attempt success
    assert a["first_try_conv"] == 2 / 7  # must never exceed final conv semantics
    assert a["recovered"] == 1           # S1 only
    pool = a["attempted"] - a["first_try_ok"]
    assert pool == 3 and a["recovered"] / pool == 1 / 3


def test_repeat_customers_scoped_per_merchant():
    m1 = q1("SELECT * FROM merchant_stats WHERE merchant_key='M1'")
    m2 = q1("SELECT * FROM merchant_stats WHERE merchant_key='M2'")
    assert m1["customers"] == 2 and m1["repeat_customers"] == 1   # C1 (3 verified), C2
    assert m2["customers"] == 1 and m2["repeat_customers"] == 0   # D1 never merged with M1 cards
    assert m1["repeat_txns"] == 3       # C1's three verified sessions (S1, S6, S9)


def test_funnel_stage_counts():
    fu = funnel("M1", *JAN)
    stages = {s["id"]: s["n"] for s in fu["stages"]}
    assert stages == {"created": 7, "attempted": 6, "settled": 4, "verified": 3}


def test_customer_period_semantics():
    cu = customers("M1", "2026-02-01", "2026-02-28")
    s = cu["summary"]
    assert s["customers"] == 1 and s["new_customers"] == 0  # C1 first paid in Jan → returning


def test_lmdi_decomposition_is_exact():
    ch = changes("M1", "2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28")
    assert ch["decomposable"]
    total = sum(ch["contrib"].values())
    assert abs(total - ch["delta_gmv"]) < 1e-6


def test_conv_drivers_sum_to_conv_change():
    ch = changes("M1", "2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28")
    dconv = ch["after"]["conv"] - ch["before"]["conv"]
    assert abs(sum(ch["conv_drivers"].values()) - dconv) < 1e-9
