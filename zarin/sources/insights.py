"""Cross-source insights: relate web signals (GA4) to payment truth (ZarinPal).

Rule of the house: NEVER a row-level join (no legitimate identity mapping), NEVER a
causal claim, NEVER merging GA4 'revenue' with payment GMV. Only aggregate,
time-window-aligned *relationships*, each carrying its methodology and caveat. If the
two sources are not both present and comparable, this returns nothing.
"""
from __future__ import annotations

_CAVEAT = ("رابطه هم‌زمانی است، نه علّی. سیگنال وب گوگل‌آنالیتیکس با حقیقت پرداخت زرین‌پال "
           "سطر‌به‌سطر ادغام نمی‌شود؛ فقط روند دو منبع در بازه‌های هم‌تراز مقایسه شده است.")

_MIN_DELTA = 0.10  # ignore sub-10% wobble as noise


def _pct_change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before


def cross_source(before: dict, after: dict) -> list[dict]:
    """`before`/`after` = {ga4_sessions, payment_sessions, payment_verified, payment_conv}."""
    out: list[dict] = []
    traffic = _pct_change(before.get("ga4_sessions"), after.get("ga4_sessions"))
    verified = _pct_change(before.get("payment_verified"), after.get("payment_verified"))
    conv = _pct_change(before.get("payment_conv"), after.get("payment_conv"))
    p_sessions = _pct_change(before.get("payment_sessions"), after.get("payment_sessions"))

    if traffic is None:
        return out

    if traffic >= _MIN_DELTA and verified is not None and verified <= 0:
        out.append(_card(
            "traffic_up_payments_flat", "ترافیک بالا رفت اما پرداخت موفق همراهش نشد",
            f"ترافیک سایت {_p(traffic)} رشد کرد، ولی پرداخت‌های موفق {_p(verified)} تغییر کرد.",
            "احتمالاً بازدیدکننده بیشتر شده اما به پرداخت موفق نرسیده — قیف پرداخت و NoAttempt را بررسی کنید.",
            "traffic→payment"))
    if traffic <= -_MIN_DELTA and conv is not None and abs(conv) < _MIN_DELTA:
        out.append(_card(
            "traffic_down_conv_stable", "ترافیک افت کرد اما نرخ تبدیل پایدار ماند",
            f"ترافیک {_p(traffic)} کم شد، نرخ تبدیل پرداخت تقریباً ثابت ({_p(conv)}).",
            "مشکل سمت جذب/ترافیک است نه پرداخت — روی منابع ترافیک تمرکز کنید.",
            "traffic→payment"))
    if traffic >= _MIN_DELTA and p_sessions is not None and p_sessions <= 0:
        out.append(_card(
            "traffic_up_intent_flat", "ترافیک رشد کرد اما جلسه‌های پرداخت زیاد نشد",
            f"ترافیک {_p(traffic)} رشد کرد ولی جلسه‌های پرداخت {_p(p_sessions)} تغییر کرد.",
            "بازدید به قصد پرداخت تبدیل نشده — مسیر رسیدن به درگاه را بررسی کنید.",
            "traffic→intent"))
    return out


def _card(cid: str, title: str, observation: str, action: str, method: str) -> dict:
    return {
        "id": cid, "kind": "cross_source", "title_fa": title,
        "observation_fa": observation, "action_fa": action,
        "methodology_fa": f"تغییر نسبی دو بازه هم‌تراز ({method}).",
        "caveat_fa": _CAVEAT, "confidence": "medium",
    }


def _p(x: float | None) -> str:
    if x is None:
        return "—"
    pct = round(x * 100)
    sign = "+" if pct >= 0 else "−"
    return f"{sign}{abs(pct)}٪"
