"""Grounded Persian business copilot.

Two-stage, deterministic-first:

  question → _plan() : intent + deterministic Persian answer + traceable evidence
           → gateway.explain() : OPTIONAL LLM rephrasing, grounding-guarded

Every number is produced by the deterministic analytics engine (`_plan`). The LLM,
when a key is present, may only make the wording friendlier — a grounding guard
rejects any answer that introduces an unsupported number, so the copilot works
identically (and correctly) with zero keys and zero network.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .ai import gateway
from .ai.provider import AIProvider
from .analytics import changes, customers, funnel, overview
from .fa import fa_money as _rial
from .fa import fa_num
from .fa import fa_pct as _pct
from .insights import generate
from .peers import benchmarks

FA_METRIC = {"conv": "نرخ تبدیل", "first_try_conv": "موفقیت در اولین تلاش",
             "no_attempt_rate": "انصراف پیش از پرداخت", "inbank_abandon_rate": "رهاشدن در بانک",
             "recovery_rate": "بازیابی پس از شکست"}


class _Plan:
    __slots__ = ("confidence", "intent", "refs", "text")

    def __init__(self, text: str, intent: str, refs: list[dict], confidence: str = "medium"):
        self.text, self.intent, self.refs, self.confidence = text, intent, refs, confidence


def _plan(m: str, question: str, f: str, t: str) -> _Plan:
    ql = question.strip()
    refs: list[dict] = []

    if re.search(r"(چرا|علت|دلیل).*(کم|افت|پایین|نزول|خراب)|افت.*(فروش|درآمد)", ql):
        d1, d2 = date.fromisoformat(f), date.fromisoformat(t)
        mid = d1 + (d2 - d1) / 2
        ch = changes(m, f, str(mid), str(mid + timedelta(days=1)), t)
        refs.append(ch["evidence"])
        if not ch["decomposable"]:
            return _Plan("در این بازه داده کافی برای تجزیه تغییر فروش وجود ندارد (یکی از دوره‌ها فروش موفق ثبت‌شده ندارد).", "changes", refs, "low")
        c = ch["contrib"]
        names = {"sessions": "تعداد جلسه‌ها", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط"}
        parts = "، ".join(f"{names[k]}: {_rial(c[k])}" for k in c)
        trend = "افت" if ch["delta_gmv"] < 0 else "رشد"
        return _Plan(
            f"بین نیمه اول و دوم این بازه، فروش موفق {_rial(abs(ch['delta_gmv']))} {trend} داشت. "
            f"سهم هر عامل: {parts}. "
            f"بزرگ‌ترین عامل: «{names[max(c, key=lambda k: abs(c[k]))]}». جزئیات در صفحه «چه چیزی تغییر کرد؟».", "changes", refs, "high")

    if re.search(r"(کی|چه ساعت|چه زمان|ساعت).*(خرید|فروش|پرداخت)", ql):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["funnel"])
        hours = [h for h in fu["hours"] if h["sessions"] >= 30]
        if not hours:
            return _Plan("داده ساعتی کافی در این بازه وجود ندارد.", "hours", refs, "low")
        peak = max(hours, key=lambda h: h["verified"])
        worst = min(hours, key=lambda h: (h["verified"] / h["sessions"]) if h["sessions"] else 1)
        return _Plan(
            f"بیشترین پرداخت موفق در ساعت {fa_num(peak['hour'])} ثبت شده ({fa_num(peak['verified'])} پرداخت). "
            f"ضعیف‌ترین نرخ تبدیل در ساعت {fa_num(worst['hour'])} است ({_pct(worst['verified']/worst['sessions'])}). "
            "توزیع کامل در صفحه «قیف پرداخت».", "hours", refs, "medium")

    if re.search(r"(پرداخت|درگاه|تراکنش).*(شکست|خطا|ناموفق|رد شد)|(شکست|خطا|ناموفق).*(بیشتر|بدتر|زیاد|پرداخت|درگاه|بانک|تراکنش)|چرا.*(شکست|خطا|ناموفق)|وضعیت (شکست|خطا)", ql):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["funnel"])
        r = fu["rates"]
        return _Plan(
            f"در این بازه: انصراف پیش از پرداخت {_pct(r['no_attempt_rate'])}، رهاشدن در بانک {_pct(r['inbank_abandon_rate'])}، "
            f"خطای صریح بانکی {_pct(r['failed_bank_rate'])}. نرخ تبدیل نهایی {_pct(r['conv'])}. "
            "این سه حالت ماهیت متفاوتی دارند و در قیف پرداخت جدا نمایش داده می‌شوند.", "friction", refs, "high")

    if re.search(r"(تلاش مجدد|بازیابی|نجات|ریکاوری|retry)", ql, re.IGNORECASE):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["recovery"])
        rec = fu["recovery"]
        return _Plan(
            f"از {fa_num(rec['first_fail_pool'])} جلسه‌ای که تلاش اولشان ناموفق بود، {fa_num(rec['recovered'])} جلسه با تلاش مجدد موفق شد "
            f"({_pct(rec['recovery_rate'])}) و {_rial(rec['recovered_gmv'])} فروش نجات یافت.", "recovery", refs, "high")

    if re.search(r"(مقایسه|همتا|رقبا|مشابه|جایگاه|رتبه)", ql):
        b = benchmarks(m, f, t)
        refs.append(b["evidence"])
        if not b["group"]["sufficient"]:
            return _Plan("تعداد پذیرندگان قابل مقایسه برای ساخت معیار همتایان کافی نیست؛ به جای عدد نامطمئن، این مقایسه نمایش داده نمی‌شود.", "peers", refs, "low")
        rows = [r for r in b["rows"] if not r["suppressed"]]
        txt = "؛ ".join(f"{FA_METRIC[r['metric']]}: صدک {fa_num(r['percentile'])} از {fa_num(r['n_peers'])} همتا" for r in rows[:3])
        return _Plan(f"گروه همتایان شما: {b['group']['rule_fa']} ({fa_num(b['group']['n'])} پذیرنده). {txt}. جزئیات و دلیل انتخاب همتایان در صفحه «همتایان».", "peers", refs, "high")

    if re.search(r"مشتری.*(برگشت|تکرار|وفادار)|(تکراری|بازگشت).*(مشتری)", ql):
        cu = customers(m, f, t)
        refs.append(cu["evidence"]["repeat"])
        s = cu["summary"]
        if not s["customers"]:
            return _Plan("در این بازه مشتری پرداخت موفقی ثبت نشده است.", "repeat", refs, "low")
        share = s["repeat_txns"] / s["txns"] if s["txns"] else None
        gshare = s["repeat_gmv"] / s["gmv"] if s["gmv"] else None
        return _Plan(
            f"{fa_num(s['customers'])} مشتری در این بازه پرداخت موفق داشتند ({fa_num(s['new_customers'])} مشتری جدید). "
            f"مشتریان تکراری {_pct(share)} از تراکنش‌ها و {_pct(gshare)} از فروش را ساخته‌اند. "
            "(تحلیل مشتری فقط پرداخت‌کنندگان موفق همین پذیرنده را می‌بیند.)", "repeat", refs, "medium")

    if re.search(r"(چه کار|چیکار|تمرکز|اولویت|این هفته|پیشنهاد|توصیه|فرصت|مهم‌ترین)", ql):
        cards = generate(m, f, t)[:3]
        for c in cards:
            refs.extend(c["evidence"][:1])
        if not cards:
            return _Plan("در این بازه هیچ فرصت قابل اتکایی با شواهد کافی پیدا نشد — این یعنی وضعیت شما به همتایان نزدیک است.", "priorities", refs, "medium")
        lines = [f"{fa_num(i+1)}) {c['title_fa']} — {c['impact_label_fa']}"
                 + (f": {_rial(c['impact_low'])} تا {_rial(c['impact_high'])}" if c["impact_high"] else "")
                 for i, c in enumerate(cards)]
        return _Plan("سه اولویت اول شما بر اساس اثر × اطمینان ÷ زحمت: " + " | ".join(lines) + ". جزئیات و شواهد در صفحه اصلی.", "priorities", refs, "high")

    ov = overview(m, f, t, None, None)
    refs.append(ov["evidence"]["gmv"])
    k = ov["kpis"]
    return _Plan(
        f"خلاصه این بازه: فروش موفق {_rial(k['gmv'])} از {fa_num(k['verified'])} پرداخت، نرخ تبدیل {_pct(k['conv'])}، "
        f"{fa_num(k['customers'])} مشتری. می‌توانید بپرسید: «چرا فروشم کم شد؟»، «مشتری‌ها کی خرید می‌کنند؟»، "
        "«شکست‌ها بدتر شده؟»، «تلاش مجدد چقدر برگرداند؟»، «در مقایسه با همتایان کجا هستم؟»، «این هفته روی چه تمرکز کنم؟»",
        "fallback", refs, "medium")


def answer(m: str, question: str, f: str, t: str, *, surface: str = "merchant",
           provider: AIProvider | None = None, use_llm: bool = True) -> dict:
    """Deterministic plan, then optional grounded LLM rephrasing. Returns the AI response contract."""
    p = _plan(m, question, f, t)
    resp = gateway.explain(
        question=question, merchant_scope=m, intent=p.intent,
        deterministic_answer_fa=p.text, evidence=p.refs, confidence=p.confidence,
        surface=surface, provider=provider, _use_default=use_llm,
    )
    return resp.to_dict()
