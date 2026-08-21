"""Deterministic fixture dataset covering the dangerous metric mistakes.

The env vars are set BEFORE any zarin import so config picks up the test marts.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="zarin_test_"))
os.environ["ZARIN_MARTS_DIR"] = str(_TMP / "marts")
os.environ["ZARIN_DATA_PATH"] = str(_TMP / "fixture.csv")
os.environ["ZARIN_TELEMETRY_DIR"] = str(_TMP / "telemetry")
# Hermetic AI: tests must be deterministic and offline. Drop any real provider/GA4
# config from the environment so the copilot runs purely on the deterministic engine;
# the key-present and transport paths are covered via explicit injection.
for _k in ("OPENROUTER_API_KEY", "GA4_PROPERTY_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ.pop(_k, None)

HEADER = ("session_key,try_seq,terminal_key,merchant_key,category_id,category_title,"
          "amount,adjusted_fee,session_status,try_status,switch_response_code,psp_code,"
          "issuer_bank_code,payer_card_key,verify_type,init_time_ms,verify_time_ms,"
          "created_at,try_created_at,verified_at,settled_at,expire_in")


def row(sk, seq, m, amount, ss, ts, *, card="", psp="PSP-1", bank="", created="2026-01-10 10:00:00",
        tcreated=None, verified="", settled="", code="", cat="10", cat_title="تست"):
    if ts == "NoAttempt":
        tcreated, psp = "", ""
    elif tcreated is None:
        tcreated = created
    return (f"{sk},{seq},T{m},{m},{cat},{cat_title},{amount},{amount//100},{ss},{ts},{code},{psp},"
            f"{bank},{card},Automated,100,,{created},{tcreated},{verified},{settled},2026-01-10 10:30:00")


ROWS = [
    # S1: verified on 3rd try (recovered). Retries must NOT inflate counts/GMV.
    row(1, 1, "M1", 100000, "Verified", "InBank"),
    row(1, 2, "M1", 100000, "Verified", "Failed", code="PSP-1:55"),
    row(1, 3, "M1", 100000, "Verified", "Verified", card="C1", bank="B1",
        verified="2026-01-10 10:05:00", settled="2026-01-10 10:04:00"),
    # S2: NoAttempt — payer never reached a PSP. NOT a bank failure.
    row(2, 0, "M1", 999999, "Failed", "NoAttempt"),
    # S3: Paid but never verified — settled money, distinct from success.
    row(3, 1, "M1", 50000, "Paid", "Paid", card="C9", bank="B1", settled="2026-01-10 10:02:00"),
    # S4: abandoned in bank.
    row(4, 1, "M1", 70000, "Failed", "InBank"),
    # S5: explicit bank failure.
    row(5, 1, "M1", 80000, "Failed", "Failed", code="PSP-1:51"),
    # S6: verified first try, repeat card C1.
    row(6, 1, "M1", 200000, "Verified", "Verified", card="C1", bank="B1",
        created="2026-01-20 12:00:00", verified="2026-01-20 12:01:00", settled="2026-01-20 12:00:30"),
    # S7: verified first try, card C2.
    row(7, 1, "M1", 300000, "Verified", "Verified", card="C2", bank="B2",
        created="2026-01-25 18:00:00", verified="2026-01-25 18:01:00", settled="2026-01-25 18:00:30"),
    # S9: February sale for decomposition test.
    row(9, 1, "M1", 400000, "Verified", "Verified", card="C1", bank="B1",
        created="2026-02-10 11:00:00", verified="2026-02-10 11:01:00", settled="2026-02-10 11:00:30"),
    # M2: separate merchant — customer scoping must not leak across merchants.
    row(8, 1, "M2", 500000, "Verified", "Verified", card="D1", bank="B1",
        created="2026-01-15 09:00:00", verified="2026-01-15 09:01:00", settled="2026-01-15 09:00:30"),
    row(10, 1, "M2", 100000, "Failed", "InBank", created="2026-02-05 09:00:00"),
    # S11: a Reversed session on M1 (Feb) — exercises the sixth outcome and the reversed
    # term of the conversion-driver identity, which must stay exact.
    row(11, 1, "M1", 120000, "Reversed", "Reversed", created="2026-02-15 13:00:00"),
    # S12: a Paid-AFTER-RETRY session on M2 (try1 fails, try2 settles but is never verified).
    # Under the correct rule recovered=Verified-only it is NOT recovered; under the old
    # Paid-inclusive rule it WOULD be. This makes test_recovered_is_verified_only able to fail.
    row(12, 1, "M2", 90000, "Paid", "Failed", created="2026-01-16 10:00:00", code="PSP-1:51"),
    row(12, 2, "M2", 90000, "Paid", "Paid", card="D2", bank="B1",
        created="2026-01-16 10:00:00", settled="2026-01-16 10:02:00"),
]


# ================================================================================================
# ZB-005 / ZB-042 fixtures: larger synthetic merchants so the peer-percentile math and the
# 6-of-9 dead card generators actually execute in tests (not just the small-sample restraint
# path). Each cohort lives in its own category_id so it never contaminates another cohort's
# peer group. All amounts within a cohort are deliberately TIED (same ticket) so the numbers
# are exactly hand-computable and — for the high-value-friction cohort — so ntile(5) actually
# needs its tiebreaker (ZB-120).
# ================================================================================================

def _bench_rows(sk, m, verified, no_attempt, filler, *, cat, cat_title, ticket=100000,
                 d="2026-03-01 10:00:00"):
    """`verified` successful sessions at `ticket`, `no_attempt` drop-offs, `filler` bank failures
    padding out to `verified+no_attempt+filler` total sessions — all on one day (so gmv_per_day
    is exact) and one category (so the peer-group band match is exact)."""
    rows = []
    for _ in range(verified):
        sk += 1
        rows.append(row(sk, 1, m, ticket, "Verified", "Verified", card=f"BC{sk}", bank="BB",
                         created=d, verified=d, settled=d, cat=cat, cat_title=cat_title))
    for _ in range(no_attempt):
        sk += 1
        rows.append(row(sk, 0, m, ticket, "Failed", "NoAttempt", created=d, cat=cat, cat_title=cat_title))
    for _ in range(filler):
        sk += 1
        rows.append(row(sk, 1, m, ticket, "Failed", "Failed", created=d, code="PSP-1:51",
                         cat=cat, cat_title=cat_title))
    return rows, sk


BENCH_PERIOD = ("2026-03-01", "2026-03-31")
# Cohort A (category 30): 8 fixed peers (BP1..BP8) + a best-end / worst-end / mid-pack target,
# every merchant at 500 sessions and a 100,000-rial ticket. conv and no_attempt_rate are set
# independently per merchant so both a higher_better=True and a higher_better=False metric can
# be hand-verified. Because the 11 merchants' GMVs (24.5M..43.0M) all sit within any one
# member's own scale+ticket band (×¼..×4), every target's peer pool is the OTHER 10 — a known,
# exactly hand-computable set.
_BENCH_A = [
    ("BP1", 250, 10), ("BP2", 275, 15), ("BP3", 300, 20), ("BP4", 325, 25),
    ("BP5", 350, 30), ("BP6", 375, 35), ("BP7", 400, 40), ("BP8", 425, 45),
    ("BEST", 430, 5), ("WORST", 245, 250), ("MID", 340, 28),
]
_sk = 20000
for _m, _v, _na in _BENCH_A:
    _rows, _sk = _bench_rows(_sk, _m, _v, _na, 500 - _v - _na, cat="30", cat_title="بنچمارک بزرگ")
    ROWS.extend(_rows)

# Cohort B (category 31): only 5 peers + 1 target — exercises the low_n (MIN_PEERS <= n < 8) flag.
_BENCH_B = [("BQ1", 200, 10), ("BQ2", 250, 20), ("BQ3", 300, 30), ("BQ4", 350, 40),
            ("BQ5", 400, 50), ("LOWN", 325, 25)]
for _m, _v, _na in _BENCH_B:
    _rows, _sk = _bench_rows(_sk, _m, _v, _na, 500 - _v - _na, cat="31", cat_title="بنچمارک کوچک")
    ROWS.extend(_rows)

# ---- ZB-042: PSP-friction fixture (category 40) --------------------------------------------
# PSP-A (80% first-try success) and PSP-B (30%) are interleaved session-key by session-key so
# ntile(3)-by-amount-band splits them evenly; the gap holds in all 3 amount terciles (all rows
# share one amount). PSP-C is a degenerate ~1.7% rail that the selection-bias guard must exclude.
# 10 Paid/Paid (never-verified) sessions on a 4th PSP double as the paid_unverified fixture.
MPSP_PERIOD = ("2026-04-01", "2026-04-30")
_D4 = "2026-04-01 10:00:00"
_sk = 30000
for _i in range(300):
    _a_ok = (_i % 5) != 4      # 80%
    _b_ok = (_i % 10) < 3      # 30%
    for _psp, _ok, _tag in (("PSP-A", _a_ok, "A"), ("PSP-B", _b_ok, "B")):
        _sk += 1
        _st = "Verified" if _ok else "Failed"
        ROWS.append(row(_sk, 1, "MPSP", 100000, _st, _st, psp=_psp, card=f"PC{_tag}{_sk}", bank="BB",
                         created=_D4, verified=_D4 if _ok else "", settled=_D4 if _ok else "",
                         code="" if _ok else "PSP-1:51", cat="40", cat_title="پی‌اس‌پی"))
for _i in range(300):
    _c_ok = _i < 5             # ~1.7% — degenerate/disabled rail
    _sk += 1
    _st = "Verified" if _c_ok else "Failed"
    ROWS.append(row(_sk, 1, "MPSP", 100000, _st, _st, psp="PSP-C", card=f"PCC{_sk}", bank="BB",
                     created=_D4, verified=_D4 if _c_ok else "", settled=_D4 if _c_ok else "",
                     code="" if _c_ok else "PSP-1:51", cat="40", cat_title="پی‌اس‌پی"))
for _i in range(10):
    _sk += 1
    ROWS.append(row(_sk, 1, "MPSP", 200000, "Paid", "Paid", psp="PSP-X", card=f"PCX{_sk}", bank="BB",
                     created=_D4, settled=_D4, cat="40", cat_title="پی‌اس‌پی"))

# ---- ZB-042/ZB-120: high-value-friction + determinism fixture (category 41) ----------------
# 400 sessions tied at 50,000 rial (90% conv) + 100 tied at 900,000 rial (40% conv, the top
# ntile(5) quintile). Every amount is tied within its group, so without the (amount, session_key)
# tiebreaker the quintile assignment — and therefore impact_high — would vary run to run (ZB-120).
MHVF_PERIOD = ("2026-05-01", "2026-05-31")
_D5 = "2026-05-01 10:00:00"
_sk = 40000
for _i in range(400):
    _ok = (_i % 10) < 9        # 90%
    _sk += 1
    _st = "Verified" if _ok else "Failed"
    ROWS.append(row(_sk, 1, "MHVF", 50000, _st, _st, psp="PSP-1", card=f"HV{_sk}", bank="BB",
                     created=_D5, verified=_D5 if _ok else "", settled=_D5 if _ok else "",
                     code="" if _ok else "PSP-1:51", cat="41", cat_title="اصطکاک بالا"))
for _i in range(100):
    _ok = (_i % 5) < 2          # 40%
    _sk += 1
    _st = "Verified" if _ok else "Failed"
    ROWS.append(row(_sk, 1, "MHVF", 900000, _st, _st, psp="PSP-1", card=f"HVB{_sk}", bank="BB",
                     created=_D5, verified=_D5 if _ok else "", settled=_D5 if _ok else "",
                     code="" if _ok else "PSP-1:51", cat="41", cat_title="اصطکاک بالا"))

# ---- ZB-042/ZB-003: absolute-funnel fixture (categories 42/43, each a lone merchant so no
# peer group ever forms — the "no usable peer group" branch _card_absolute_funnel exists for) --
BROKEN_PERIOD = ("2026-06-01", "2026-06-30")
_D6 = "2026-06-01 10:00:00"
_sk = 50000
for _i in range(45):   # MBROKEN: na=75%, conv=25% — objectively broken funnel
    _sk += 1
    ROWS.append(row(_sk, 0, "MBROKEN", 80000, "Failed", "NoAttempt", created=_D6, cat="42", cat_title="بحرانی"))
for _i in range(15):
    _sk += 1
    ROWS.append(row(_sk, 1, "MBROKEN", 80000, "Verified", "Verified", psp="PSP-1", card=f"MB{_sk}", bank="BB",
                     created=_D6, verified=_D6, settled=_D6, cat="42", cat_title="بحرانی"))
for _i in range(3):     # MHEALTHY: na=5%, conv=85% — must NOT trigger the absolute-funnel alert
    _sk += 1
    ROWS.append(row(_sk, 0, "MHEALTHY", 80000, "Failed", "NoAttempt", created=_D6, cat="43", cat_title="سالم"))
for _i in range(51):
    _sk += 1
    ROWS.append(row(_sk, 1, "MHEALTHY", 80000, "Verified", "Verified", psp="PSP-1", card=f"MH{_sk}", bank="BB",
                     created=_D6, verified=_D6, settled=_D6, cat="43", cat_title="سالم"))
for _i in range(6):
    _sk += 1
    ROWS.append(row(_sk, 1, "MHEALTHY", 80000, "Failed", "Failed", code="PSP-1:51",
                     created=_D6, cat="43", cat_title="سالم"))


def _build_once():
    csv = Path(os.environ["ZARIN_DATA_PATH"])
    csv.write_text(HEADER + "\n" + "\n".join(ROWS) + "\n", encoding="utf-8")
    from zarin.pipeline import build
    build(data_path=csv, out_dir=Path(os.environ["ZARIN_MARTS_DIR"]), quiet=True)
    from zarin.db import reset
    reset()


_build_once()
