"""ZB-005: the peer percentile happy path — only the suppressed branch had coverage before.

Uses the synthetic cohorts built in conftest.py (category 30 = BP1..BP8 + BEST/WORST/MID,
category 31 = BQ1..BQ5 + LOWN). Every assertion below is a value computed by hand from the
fixture's own session counts (see conftest.py's _BENCH_A / _BENCH_B tables), not from a
tolerance-based sanity check — a polarity inversion, an off-by-one in `better`, or a broken
`_quantile` interpolation each break a specific assertion here.
"""
import pytest

from tests.conftest import BENCH_PERIOD
from zarin.peers import _quantile, benchmarks, peer_group

MAR = BENCH_PERIOD


def test_quantile_interpolates_between_neighbors():
    """_quantile on a 10-value list at p=.25/.50/.75 lands at fractional indices (2.25/4.5/6.75)
    — by hand: p25 = 0.55 + .25*(0.60-0.55) = 0.5625; p50 = 0.65 + .5*(0.68-0.65) = 0.665;
    p75 = 0.70 + .75*(0.75-0.70) = 0.7375."""
    vals = [0.49, 0.50, 0.55, 0.60, 0.65, 0.68, 0.70, 0.75, 0.80, 0.85]
    assert _quantile(vals, 0.25) == pytest.approx(0.5625)
    assert _quantile(vals, 0.50) == pytest.approx(0.665)
    assert _quantile(vals, 0.75) == pytest.approx(0.7375)
    # boundary cases: p=0 and p=1 must return the extremes exactly, no interpolation
    assert _quantile(vals, 0.0) == vals[0]
    assert _quantile(vals, 1.0) == vals[-1]


def test_peer_group_picks_scale_ticket_level_with_full_pool():
    """BEST's own gmv/ticket band is wide enough to catch all 10 other cohort-A merchants, so
    peer_group must resolve at the tightest ('scale+ticket') level, not fall back."""
    g = peer_group("BEST")
    assert g["level"] == "scale+ticket"
    assert g["n"] == 10
    assert g["sufficient"] is True


def test_percentile_best_end_both_orientations():
    """BEST has the highest conv (0.86, higher_better=True) AND the lowest no_attempt_rate
    (0.01, higher_better=False) of the 11-merchant cohort — both must read percentile=100."""
    b = benchmarks("BEST", *MAR)
    rows = {r["metric"]: r for r in b["rows"]}
    conv = rows["conv"]
    assert not conv["suppressed"]
    assert conv["higher_better"] is True
    assert conv["n_peers"] == 10
    assert conv["low_n"] is False
    assert conv["percentile"] == 100
    assert conv["p25"] == pytest.approx(0.5625)
    assert conv["p50"] == pytest.approx(0.665)
    assert conv["p75"] == pytest.approx(0.7375)

    na = rows["no_attempt_rate"]
    assert na["higher_better"] is False
    assert na["percentile"] == 100  # lowest no_attempt_rate = best, under the lower-is-better rule


def test_percentile_worst_end_both_orientations():
    """WORST has the lowest conv (0.49) and the highest no_attempt_rate (0.50) — both must
    read percentile=0, proving the (mine > v) == higher_better polarity is not inverted."""
    b = benchmarks("WORST", *MAR)
    rows = {r["metric"]: r for r in b["rows"]}
    assert rows["conv"]["percentile"] == 0
    assert rows["no_attempt_rate"]["percentile"] == 0
    assert rows["conv"]["n_peers"] == 10


def test_percentile_mid_pack():
    """MID's conv (0.68) beats exactly 5 of its 10 peers (0.49/0.50/0.55/0.60/0.65) ->
    round(100*5/10) = 50. Its no_attempt_rate (0.056) beats exactly 5 of 10 too."""
    b = benchmarks("MID", *MAR)
    rows = {r["metric"]: r for r in b["rows"]}
    assert rows["conv"]["percentile"] == 50
    assert rows["no_attempt_rate"]["percentile"] == 50
    assert rows["conv"]["n_peers"] == 10


def test_low_n_flag_between_min_and_preferred_pool():
    """LOWN's category has only 5 same-scale peers (BQ1..BQ5): sufficient (>= MIN_PEERS=5) but
    below PREFERRED_PEERS=8, so low_n must be True while the row is still usable."""
    b = benchmarks("LOWN", *MAR)
    rows = {r["metric"]: r for r in b["rows"]}
    conv = rows["conv"]
    assert conv["n_peers"] == 5
    assert not conv["suppressed"]
    assert conv["low_n"] is True
    # hand-computed: conv 0.65 beats BQ1(0.40)/BQ2(0.50)/BQ3(0.60) = 3 of 5 -> 60%
    assert conv["percentile"] == 60
    na = rows["no_attempt_rate"]
    assert na["low_n"] is True
    # na 0.05 beats (is lower than) BQ3(0.06)/BQ4(0.08)/BQ5(0.10) = 3 of 5 -> 60%
    assert na["percentile"] == 60
