"""Deterministic fixture dataset covering the dangerous metric mistakes.

The env vars are set BEFORE any zarin import so config picks up the test marts.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="zarin_test_"))
os.environ["ZARIN_MARTS_DIR"] = str(_TMP / "marts")
os.environ["ZARIN_DATA_PATH"] = str(_TMP / "fixture.csv")

HEADER = ("session_key,try_seq,terminal_key,merchant_key,category_id,category_title,"
          "amount,adjusted_fee,session_status,try_status,switch_response_code,psp_code,"
          "issuer_bank_code,payer_card_key,verify_type,init_time_ms,verify_time_ms,"
          "created_at,try_created_at,verified_at,settled_at,expire_in")


def row(sk, seq, m, amount, ss, ts, *, card="", psp="PSP-1", bank="", created="2026-01-10 10:00:00",
        tcreated=None, verified="", settled="", code=""):
    if ts == "NoAttempt":
        tcreated, psp = "", ""
    elif tcreated is None:
        tcreated = created
    return (f"{sk},{seq},T{m},{m},10,تست,{amount},{amount//100},{ss},{ts},{code},{psp},"
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
]


def _build_once():
    csv = Path(os.environ["ZARIN_DATA_PATH"])
    csv.write_text(HEADER + "\n" + "\n".join(ROWS) + "\n", encoding="utf-8")
    from zarin.pipeline import build
    build(data_path=csv, out_dir=Path(os.environ["ZARIN_MARTS_DIR"]), quiet=True)
    from zarin.db import reset
    reset()


_build_once()
