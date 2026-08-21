"""ZB-041: the old LMDI test only asserted closure (Σ contrib == ΔGMV), a property that holds
for ANY assignment of factor series to labels — so a refactor that swapped which series feeds
`contrib['sessions']` vs `contrib['ticket']` would still pass it. These tests isolate one factor
at a time via a monkeypatched `period_agg`, so each one pins a SPECIFIC contrib key to a SPECIFIC
value. If `changes()`'s factor wiring were permuted (e.g. contrib['sessions'] computed from the
ticket series instead), `test_lmdi_isolates_*` would fail: the isolated test expects the moved
factor's contribution to equal essentially all of delta_gmv and the other two to be ~0, so
feeding the wrong series into a label flips which key holds the ~0s and which holds delta_gmv.
"""
import math

import pytest

from zarin import analytics

JAN = ("2026-01-01", "2026-01-31")
FEB = ("2026-02-01", "2026-02-28")


def _period(sessions, conv, ticket):
    """A period_agg()-shaped dict with gmv = sessions * conv * ticket exactly, so ONLY the
    factor(s) that actually change between two calls should get a non-zero LMDI contribution."""
    verified = sessions * conv
    gmv = verified * ticket
    na, inbank, fbank, pu, rev = (sessions * r for r in (0.10, 0.05, 0.03, 0.01, 0.01))
    return {
        "sessions": sessions, "attempted": sessions * 0.9, "verified": verified,
        "no_attempt": na, "abandoned_inbank": inbank, "failed_bank": fbank,
        "paid_unverified": pu, "paid_unverified_amount": pu * ticket,
        "reversed": rev, "recovered": 0, "first_try_ok": verified, "first_try_verified": verified,
        "gmv": gmv, "fee_index_sum": 0,
        "conv": conv, "attempt_rate": 0.9, "no_attempt_rate": na / sessions,
        "inbank_abandon_rate": inbank / sessions, "failed_bank_rate": fbank / sessions,
        "first_try_conv": conv, "avg_ticket": ticket,
    }


def _patched_changes(monkeypatch, before, after):
    calls = iter([before, after])
    monkeypatch.setattr(analytics, "period_agg", lambda *a, **k: next(calls))
    return analytics.changes("MX", *JAN, *FEB)


def test_lmdi_isolates_sessions_factor(monkeypatch):
    """Only sessions moves (1000 -> 2000); conv and ticket held constant. Because
    gmv = sessions*conv*ticket here, delta_gmv/g1 == sessions2/sessions1 exactly, so the
    closed-form LMDI contribution of the moved factor equals delta_gmv exactly and the other
    two factors' ln(x2/x1) == ln(1) == 0."""
    before, after = _period(1000, 0.50, 100_000), _period(2000, 0.50, 100_000)
    ch = _patched_changes(monkeypatch, before, after)
    assert ch["decomposable"]
    assert ch["contrib"]["sessions"] == pytest.approx(ch["delta_gmv"], rel=1e-9)
    assert ch["contrib"]["conv"] == pytest.approx(0, abs=1e-6)
    assert ch["contrib"]["ticket"] == pytest.approx(0, abs=1e-6)


def test_lmdi_isolates_conv_factor(monkeypatch):
    """Only conv moves (0.40 -> 0.60); sessions and ticket held constant."""
    before, after = _period(1000, 0.40, 100_000), _period(1000, 0.60, 100_000)
    ch = _patched_changes(monkeypatch, before, after)
    assert ch["contrib"]["conv"] == pytest.approx(ch["delta_gmv"], rel=1e-9)
    assert ch["contrib"]["sessions"] == pytest.approx(0, abs=1e-6)
    assert ch["contrib"]["ticket"] == pytest.approx(0, abs=1e-6)


def test_lmdi_isolates_ticket_factor(monkeypatch):
    """Only ticket moves (100,000 -> 150,000); sessions and conv held constant."""
    before, after = _period(1000, 0.50, 100_000), _period(1000, 0.50, 150_000)
    ch = _patched_changes(monkeypatch, before, after)
    assert ch["contrib"]["ticket"] == pytest.approx(ch["delta_gmv"], rel=1e-9)
    assert ch["contrib"]["sessions"] == pytest.approx(0, abs=1e-6)
    assert ch["contrib"]["conv"] == pytest.approx(0, abs=1e-6)


def test_lmdi_mixed_window_dominant_factor_and_sign(monkeypatch):
    """A window built so ticket swings much harder (relative log-change) than sessions or conv:
    sessions -10% (0.9x), conv +10% (1.1x), ticket +300% (4x). ticket's |ln(ratio)| (ln4≈1.386)
    dwarfs sessions' (|ln0.9|≈0.105) and conv's (ln1.1≈0.095), so ticket must dominate and its
    sign must be positive (GMV grew). This fails if contrib['ticket'] were swapped with either
    sibling: the swapped-in series has a tiny ln-ratio, so the dominant slot would show ~0 instead."""
    before = _period(1000, 0.50, 100_000)
    after = _period(900, 0.55, 400_000)
    ch = _patched_changes(monkeypatch, before, after)
    assert ch["decomposable"]
    assert ch["delta_gmv"] > 0
    dominant = max(ch["contrib"], key=lambda k: abs(ch["contrib"][k]))
    assert dominant == "ticket"
    assert ch["contrib"]["ticket"] > 0
    assert abs(ch["contrib"]["ticket"]) > abs(ch["contrib"]["sessions"])
    assert abs(ch["contrib"]["ticket"]) > abs(ch["contrib"]["conv"])
    # closure must still hold on the mixed window
    assert sum(ch["contrib"].values()) == pytest.approx(ch["delta_gmv"], rel=1e-9)


def test_lmdi_contrib_matches_closed_form_by_hand():
    """Direct hand-check of `_lmdi_contrib` itself (not through changes()): for g1=100,g2=200,
    x1=1,x2=2 the log-mean L = (200-100)/ln(2) = 144.2695..., contrib = L*ln(2) = 100 exactly
    (since here the whole 100 gmv delta is attributed to this one factor moving 1->2)."""
    L = (200 - 100) / math.log(2)
    expected = L * math.log(2)
    assert analytics._lmdi_contrib(100, 200, 1, 2) == pytest.approx(expected)
    assert analytics._lmdi_contrib(100, 200, 1, 2) == pytest.approx(100, rel=1e-9)
    # a factor that does not move contributes exactly 0
    assert analytics._lmdi_contrib(100, 200, 5, 5) == 0.0
