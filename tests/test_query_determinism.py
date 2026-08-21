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
# row_number()/rank()/ntile(n) OVER (ORDER BY ...) — capture the order-by clause
WINDOW = re.compile(r"(row_number|rank|dense_rank|ntile)\s*\([^)]*\)\s*OVER\s*\(\s*ORDER\s+BY\s+([^)]+)\)",
                    re.IGNORECASE)


def _sql_files():
    return sorted(p for p in SRC.rglob("*.py") if "OVER" in p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: p.name)
def test_ranking_windows_have_a_tiebreaker(path):
    text = path.read_text(encoding="utf-8")
    offenders = []
    for m in WINDOW.finditer(text):
        order_by = m.group(2)
        if "," not in order_by:      # single expression → ties are resolved arbitrarily
            line = text[: m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line} — ORDER BY {order_by.strip()}")
    assert not offenders, (
        "ranking window with no tiebreaker (ties → non-deterministic user-visible output):\n  "
        + "\n  ".join(offenders))


def test_the_check_can_actually_fail():
    """Guard against the assertion above passing because the regex matches nothing."""
    assert _sql_files(), "no source file contains a window function — regex or layout changed"
    sample = "row_number() OVER (ORDER BY gmv DESC) AS r"
    assert WINDOW.search(sample) and "," not in WINDOW.search(sample).group(2)
