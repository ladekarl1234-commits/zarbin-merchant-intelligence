"""Deterministic Persian business copilot.

No LLM: questions are routed by intent patterns to the same analytical engine
that powers the rest of the product, so every number in an answer is traceable.
This keeps the project runnable by judges with zero keys and zero network.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .analytics import changes, customers, funnel, overview
from .insights import generate
from .peers import benchmarks

FA_METRIC = {"conv": "نرخ تبدیل", "first_try_conv": "موفقیت در اولین تلاش",
             "no_attempt_rate": "انصراف پیش از پرداخت", "inbank_abandon_rate": "رهاشدن در بانک",
             "recovery_rate": "بازیابی پس از شکست"}


def _rial(v) -> str:
    return f"{v:,.0f} ریال" if v is not None else "—"


def _pct(v) -> str:
    return f"{v*100:.1f}٪" if v is not None else "—"


def answer(m: str, question: str, f: str, t: str) -> dict:
    ql = question.strip()
    refs: list[dict] = []

    def done(text, intent):
        return {"answer_fa": text, "intent": intent, "evidence": refs,
                "note_fa": "این پاسخ توسط موتور تحلیلی قطعی تولید شده است، نه مدل زبانی؛ همه اعداد قابل ردیابی‌اند."}

    if re.search(r"(چرا|علت|دلیل).*(کم|افت|پایین|نزول|خراب)|افت.*(فروش|درآمد)", ql):
        d1, d2 = date.fromisoformat(f), date.fromisoformat(t)
        mid = d1 + (d2 - d1) / 2
        ch = changes(m, f, str(mid), str(mid + timedelta(days=1)), t)
        refs.append(ch["evidence"])
        if not ch["decomposable"]:
            return done("در این بازه داده کافی برای تجزیه تغییر فروش وجود ندارد (یکی از دوره‌ها فروش موفق ثبت‌شده ندارد).", "changes")
        c = ch["contrib"]
        names = {"sessions": "تعداد جلسه‌ها", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط"}
        parts = "، ".join(f"{names[k]}: {c[k]:,.0f} ریال" for k in c)
        trend = "افت" if ch["delta_gmv"] < 0 else "رشد"
        return done(
            f"بین نیمه اول و دوم این بازه، فروش موفق {abs(ch['delta_gmv']):,.0f} ریال {trend} داشت. "
            f"تجزیه دقیق (LMDI) سهم هر عامل: {parts}. "
            f"بزرگ‌ترین عامل: «{names[max(c, key=lambda k: abs(c[k]))]}». جزئیات در صفحه «چه چیزی تغییر کرد؟».", "changes")

    if re.search(r"(کی|چه ساعت|چه زمان|ساعت).*(خرید|فروش|پرداخت)", ql):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["funnel"])
        hours = [h for h in fu["hours"] if h["sessions"] >= 30]
        if not hours:
            return done("داده ساعتی کافی در این بازه وجود ندارد.", "hours")
        peak = max(hours, key=lambda h: h["verified"])
        worst = min(hours, key=lambda h: (h["verified"] / h["sessions"]) if h["sessions"] else 1)
        return done(
            f"بیشترین پرداخت موفق در ساعت {peak['hour']} ثبت شده ({peak['verified']:,} پرداخت). "
            f"ضعیف‌ترین نرخ تبدیل در ساعت {worst['hour']} است ({_pct(worst['verified']/worst['sessions'])}). "
            "توزیع کامل در صفحه «قیف پرداخت».", "hours")

    if re.search(r"(شکست|خطا|ناموفق).*(بیشتر|بدتر|زیاد)|وضعیت (شکست|خطا)", ql):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["funnel"])
        r = fu["rates"]
        return done(
            f"در این بازه: انصراف پیش از پرداخت {_pct(r['no_attempt_rate'])}، رهاشدن در بانک {_pct(r['inbank_abandon_rate'])}، "
            f"خطای صریح بانکی {_pct(r['failed_bank_rate'])}. نرخ تبدیل نهایی {_pct(r['conv'])}. "
            "این سه حالت ماهیت متفاوتی دارند و در قیف پرداخت جدا نمایش داده می‌شوند.", "friction")

    if re.search(r"(تلاش مجدد|بازیابی|نجات|ریکاوری|retry)", ql, re.I):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["recovery"])
        rec = fu["recovery"]
        return done(
            f"از {rec['first_fail_pool']:,} جلسه‌ای که تلاش اولشان ناموفق بود، {rec['recovered']:,} جلسه با تلاش مجدد موفق شد "
            f"({_pct(rec['recovery_rate'])}) و {_rial(rec['recovered_gmv'])} فروش نجات یافت.", "recovery")

    if re.search(r"(مقایسه|همتا|رقبا|مشابه|جایگاه|رتبه)", ql):
        b = benchmarks(m, f, t)
        refs.append(b["evidence"])
        if not b["group"]["sufficient"]:
            return done("تعداد پذیرندگان قابل مقایسه برای ساخت معیار همتایان کافی نیست؛ به جای عدد نامطمئن، این مقایسه نمایش داده نمی‌شود.", "peers")
        rows = [r for r in b["rows"] if not r["suppressed"]]
        txt = "؛ ".join(f"{FA_METRIC[r['metric']]}: صدک {r['percentile']} از {r['n_peers']} همتا" for r in rows[:3])
        return done(f"گروه همتایان شما: {b['group']['rule_fa']} ({b['group']['n']} پذیرنده). {txt}. جزئیات و دلیل انتخاب همتایان در صفحه «همتایان».", "peers")

    if re.search(r"مشتری.*(برگشت|تکرار|وفادار)|(تکراری|بازگشت).*(مشتری)", ql):
        cu = customers(m, f, t)
        refs.append(cu["evidence"]["repeat"])
        s = cu["summary"]
        if not s["customers"]:
            return done("در این بازه مشتری پرداخت موفقی ثبت نشده است.", "repeat")
        share = s["repeat_txns"] / s["txns"] if s["txns"] else None
        gshare = s["repeat_gmv"] / s["gmv"] if s["gmv"] else None
        return done(
            f"{s['customers']:,} مشتری در این بازه پرداخت موفق داشتند ({s['new_customers']:,} مشتری جدید). "
            f"مشتریان تکراری {_pct(share)} از تراکنش‌ها و {_pct(gshare)} از فروش را ساخته‌اند. "
            "(تحلیل مشتری فقط پرداخت‌کنندگان موفق همین پذیرنده را می‌بیند.)", "repeat")

    if re.search(r"(چه کار|چیکار|تمرکز|اولویت|این هفته|پیشنهاد|توصیه)", ql):
        cards = generate(m, f, t)[:3]
        for c in cards:
            refs.extend(c["evidence"][:1])
        if not cards:
            return done("در این بازه هیچ فرصت قابل اتکایی با شواهد کافی پیدا نشد — این یعنی وضعیت شما به همتایان نزدیک است.", "priorities")
        lines = [f"{i+1}) {c['title_fa']} — {c['impact_label_fa']}"
                 + (f": {c['impact_low']:,.0f} تا {c['impact_high']:,.0f} ریال" if c["impact_high"] else "")
                 for i, c in enumerate(cards)]
        return done("سه اولویت اول شما بر اساس اثر × اطمینان ÷ زحمت: " + " | ".join(lines) + ". جزئیات و شواهد در صفحه اصلی.", "priorities")

    ov = overview(m, f, t, None, None)
    refs.append(ov["evidence"]["gmv"])
    k = ov["kpis"]
    return {
        "answer_fa": (
            f"خلاصه این بازه: فروش موفق {_rial(k['gmv'])} از {k['verified']:,} پرداخت، نرخ تبدیل {_pct(k['conv'])}، "
            f"{k['customers']:,} مشتری. می‌توانید بپرسید: «چرا فروشم کم شد؟»، «مشتری‌ها کی خرید می‌کنند؟»، "
            "«شکست‌ها بدتر شده؟»، «تلاش مجدد چقدر برگرداند؟»، «در مقایسه با همتایان کجا هستم؟»، «این هفته روی چه تمرکز کنم؟»"),
        "intent": "fallback", "evidence": refs,
        "note_fa": "این پاسخ توسط موتور تحلیلی قطعی تولید شده است، نه مدل زبانی؛ همه اعداد قابل ردیابی‌اند.",
    }
