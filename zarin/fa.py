"""Persian text formatting for server-generated sentences (insights, copilot)."""
from __future__ import annotations

_FA_DIGITS = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹،٫")


def fa_digits(s: str) -> str:
    return s.translate(_FA_DIGITS)


def fa_num(v: float | None) -> str:
    if v is None:
        return "—"
    return fa_digits(f"{round(v):,}")


def fa_money(v: float | None) -> str:
    """Compact IRR in Persian: ۶۱٫۸ میلیارد ریال / ۴۱٫۴ میلیون ریال."""
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        s = f"{v/1e12:,.2f} هزار میلیارد"
    elif a >= 1e9:
        s = f"{v/1e9:,.1f} میلیارد"
    elif a >= 1e6:
        s = f"{v/1e6:,.1f} میلیون"
    elif a >= 1e4:
        s = f"{v/1e3:,.0f} هزار"
    else:
        s = f"{v:,.0f}"
    return fa_digits(s) + " ریال"


def fa_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return fa_digits(f"{v*100:.{digits}f}") + "٪"
