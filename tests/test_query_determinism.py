"""Every ranking window function must impose a TOTAL order.

ZB-120 was one instance of a class: `ntile(5) OVER (ORDER BY amount)` over 17k tied amounts
put the same session in a different band between runs, so a merchant's dashboard changed
without the data changing. Fixing the reported instance is not the fix — an adversarial
verifier then found five more `row_number() OVER (ORDER BY <col> DESC)` driving user-visible
merchant ranks, with 26 tied groups in `repeat_txns` alone.

So this test binds the class instead of the instances: a window function that ranks rows must
order by something unique (a key), not only by a value that ties. It is a static check on the
SQL text, which means it also fails for code written after this one, not just for today's.
"""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "zarin"
# row_number()/rank()/ntile(n) OVER ([PARTITION BY ...] ORDER BY ...) — capture the order-by clause.
# The PARTITION BY branch is not optional decoration: without it the regex silently matched NOTHING
# for partitioned windows, so they were invisible to this check rather than merely weakly checked.
WINDOW = re.compile(
    r"(row_number|rank|dense_rank|ntile)\s*\([^)]*\)\s*OVER\s*\(\s*"
    r"(?:PARTITION\s+BY[^)]*?)?ORDER\s+BY\s+([^)]+)\)", re.IGNORECASE)
# Columns that are unique within their query's grain, so ordering by one is a TOTAL order.
# Requiring merely "a comma" is not enough — `ORDER BY gmv DESC, sessions` has one and still ties.
KEY_COLUMNS = ("session_key", "merchant_key", "payer_card_key", "code", "band", "hour")


def _sql_files():
    return sorted(p for p in SRC.rglob("*.py") if "OVER" in p.read_text(encoding="utf-8"))


def _resolves_ties(order_by: str) -> bool:
    """True if a unique key appears ANYWHERE in the ordering — not merely if a comma is present.

    Position matters less than presence: once the ordering reaches a unique key the order is
    already total, so terms after it cannot reintroduce a tie. Checking only the last term
    wrongly failed `ORDER BY amount, session_key, try_seq`, which is perfectly deterministic.
    """
    for term in order_by.split(","):
        t = term.strip().lower()
        t = re.sub(r"\s+(asc|desc)$", "", re.sub(r"\s+nulls\s+(first|last)$", "", t)).strip()
        if t in KEY_COLUMNS:
            return True
    return False


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: p.name)
def test_ranking_windows_have_a_tiebreaker(path):
    text = path.read_text(encoding="utf-8")
    offenders = []
    for m in WINDOW.finditer(text):
        if not _resolves_ties(m.group(2)):
            line = text[: m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line} — ORDER BY {m.group(2).strip()}")
    assert not offenders, (
        "ranking window whose ORDER BY cannot break ties (→ non-deterministic user-visible "
        "output). End it with a unique key:\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("sql,ok", [
    ("row_number() OVER (ORDER BY gmv DESC) AS r", False),                    # no tiebreaker
    ("row_number() OVER (ORDER BY gmv DESC, sessions) AS r", False),          # comma, still ties
    ("row_number() OVER (PARTITION BY m ORDER BY gmv DESC) AS r", False),     # was invisible
    ("row_number() OVER (ORDER BY gmv DESC, merchant_key) AS r", True),
    ("ntile(5) OVER (ORDER BY amount, session_key) AS band", True),
    ("ntile(5) OVER (ORDER BY amount, session_key, try_seq) AS band", True),   # key not last
    ("row_number() OVER (PARTITION BY m ORDER BY gmv DESC NULLS LAST, merchant_key) AS r", True),
])
def test_the_check_can_actually_fail(sql, ok):
    """A static check that matches nothing passes vacuously. Pin what it accepts and rejects —
    including the three shapes an adversarial verifier used to slip past the first version."""
    m = WINDOW.search(sql)
    assert m, f"regex did not match at all: {sql}"
    assert _resolves_ties(m.group(2)) is ok, sql


def test_there_is_something_to_check():
    assert _sql_files(), "no source file contains a window function — regex or layout changed"
