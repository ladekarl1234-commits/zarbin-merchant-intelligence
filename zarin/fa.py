"""Persian text formatting for server-generated sentences (insights, copilot)."""
from __future__ import annotations

# Thousands separator is U+066C (ARABIC THOUSANDS SEPARATOR), which is what `Intl` emits for
# fa-IR in the frontend. This module previously used U+060C (ARABIC COMMA), so the SAME number
# rendered differently depending on whether the backend or the frontend formatted it — visible
# in one screen, e.g. a copilot sentence next to a KPI tile (ZB-043).
_FA_DIGITS = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")


def fa_digits(s: str) -> str:
    return s.translate(_FA_DIGITS)


def _max_frac(v: float, digits: int) -> str:
    """Format like `Intl.NumberFormat(maximumFractionDigits: digits)`: keep up to `digits`
    decimals but drop trailing zeros, so 50.0 → "50" and 2.00 → "2" (ZB-043 parity)."""
    s = f"{v:,.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s




def fa_num(v: float | None) -> str:
    if v is None:
        return "—"
    return fa_digits(f"{round(v):,}")


def fa_money(v: float | None) -> str:
    """Compact IRR in Persian: ۶۱٫۸ میلیارد ریال / ۴۱٫۴ میلیون ریال."""
    if v is None:
        return "—"
    a = abs(v)
    # `_trim0` keeps these identical to the frontend's Intl output («۱ میلیون», not «۱٫۰ میلیون»)
    if a >= 1e12:
        s = _max_frac(v / 1e12, 2) + " هزار میلیارد"
    elif a >= 1e9:
        s = _max_frac(v / 1e9, 1) + " میلیارد"
    elif a >= 1e6:
        s = _max_frac(v / 1e6, 1) + " میلیون"
    elif a >= 1e4:
        s = f"{v/1e3:,.0f} هزار"
    else:
        s = f"{v:,.0f}"
    return fa_digits(s) + " ریال"


def fa_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return fa_digits(_max_frac(v * 100, digits)) + "٪"
