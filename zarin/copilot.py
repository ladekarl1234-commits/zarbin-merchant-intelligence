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
from .insights import _card_psp_friction, _Ctx, _period_tickets, format_impact, generate
from .peers import benchmarks, peer_group

FA_METRIC = {"conv": "نرخ تبدیل", "first_try_conv": "موفقیت در اولین تلاش",
             "no_attempt_rate": "انصراف پیش از پرداخت", "inbank_abandon_rate": "رهاشدن در بانک",
             "recovery_rate": "بازیابی پس از شکست"}


class _Plan:
    __slots__ = ("confidence", "intent", "refs", "text")

    def __init__(self, text: str, intent: str, refs: list[dict], confidence: str = "medium"):
        self.text, self.intent, self.refs, self.confidence = text, intent, refs, confidence


# Questions the engine genuinely cannot answer. Saying so is the correct behaviour — answering a
# DIFFERENT question with a confident business summary is what the audit flagged (ZB-032/ZB-040).
_OUT_OF_SCOPE = (
    (r"(فردا|هفته آینده|ماه آینده|سال آینده|پیش.?بینی|پیش.?بین|چقدر می.?شود|خواهد شد)", "forecast"),
    (r"(نرخ ارز|دلار|یورو|طلا|بورس|سهام|بیت.?کوین|ارز دیجیتال)", "external_market"),
    (r"(شماره کارت|شماره تماس|شماره موبایل|کد ملی|ایمیل|آدرس|نام مشتری|اسم مشتری)", "pii"),
    (r"^\s*(سلام|درود|خداحافظ|ممنون|مرسی|تشکر|چطوری|خوبی)\W*$", "greeting"),
)
_SCOPE_HINT = ("می‌توانم دربارهٔ فروش موفق، مسیر پرداخت و دلیل شکست‌ها، مقایسه با کسب‌وکارهای مشابه، "
               "مشتریان و بازگشتشان، تلاش مجدد، درگاه‌های بانکی و اولویت‌های این هفته پاسخ بدهم.")
# The business vocabulary the engine actually models — used to tell "I didn't understand this
# phrasing of a business question" apart from "this is not a question about your payments".
_BUSINESS = r"(فروش|درآمد|پرداخت|تراکنش|مشتری|درگاه|بانک|تبدیل|کارمزد|سبد|خرید|جلسه|تایید|برگشت|قیف|همتا|رقیب|مشابه)"


def _equal_halves(f: str, t: str):
    """Split [f, t] into two EQUAL windows, dropping the middle day on an odd span.

    An odd span used to be split unevenly, so the sessions factor carried an extra day and the
    decomposition was biased (ZB-018). Returns None when the window is too short to halve.
    """
    d1, d2 = date.fromisoformat(f), date.fromisoformat(t)
    n_days = (d2 - d1).days + 1
    if n_days < 28:
        return None
    half = n_days // 2
    return str(d1 + timedelta(days=half - 1)), str(d2 - timedelta(days=half - 1)), half


def _plan(m: str, question: str, f: str, t: str) -> _Plan:
    ql = question.strip()
    refs: list[dict] = []

    for pattern, _kind in _OUT_OF_SCOPE:
        if re.search(pattern, ql):
            return _Plan("این پرسش خارج از چیزی است که از داده پرداخت‌های شما قابل محاسبه است. " + _SCOPE_HINT,
                         "out_of_scope", refs, "low")

    if re.search(r"(چرا|علت|دلیل).*(کم|افت|پایین|نزول|خراب)|افت.*(فروش|درآمد)", ql):
        halves = _equal_halves(f, t)
        if not halves:
            return _Plan("بازه انتخابی برای مقایسه دو نیمه کوتاه است (حداقل ۲۸ روز لازم است).", "changes", refs, "low")
        a_end, b_start, half = halves
        ch = changes(m, f, a_end, b_start, t)
        refs.append(ch["evidence"])
        if not ch["decomposable"]:
            return _Plan("در این بازه داده کافی برای تجزیه تغییر فروش وجود ندارد (یکی از دوره‌ها فروش موفق ثبت‌شده ندارد).", "changes", refs, "low")
        c = ch["contrib"]
        names = {"sessions": "تعداد جلسه‌ها", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط"}
        parts = "، ".join(f"{names[k]}: {_rial(c[k])}" for k in c)
        trend = "افت" if ch["delta_gmv"] < 0 else "رشد"
        return _Plan(
            f"بین دو نیمهٔ {fa_num(half)} روزهٔ این بازه، فروش موفق {_rial(abs(ch['delta_gmv']))} {trend} داشت. "
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

    # recovery is matched BEFORE friction: a question like "چقدر از تراکنش‌های ناموفق نجات
    # پیدا کرد؟" contains both a failure word and a recovery word; recovery is the intent.
    if re.search(r"(تلاش مجدد|بازیابی|نجات|ریکاوری|retry)", ql, re.IGNORECASE):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["recovery"])
        rec = fu["recovery"]
        return _Plan(
            f"از {fa_num(rec['first_fail_pool'])} جلسه‌ای که تلاش اولشان ناموفق بود، {fa_num(rec['recovered'])} جلسه با تلاش مجدد موفق شد "
            f"({_pct(rec['recovery_rate'])}) و {_rial(rec['recovered_gmv'])} فروش نجات یافت.", "recovery", refs, "high")

    if re.search(r"(پرداخت|درگاه|تراکنش).*(شکست|خطا|ناموفق|رد شد)|(شکست|خطا|ناموفق).*(بیشتر|بدتر|زیاد|پرداخت|درگاه|بانک|تراکنش)|چرا.*(شکست|خطا|ناموفق)|وضعیت (شکست|خطا)", ql):
        fu = funnel(m, f, t)
        refs.append(fu["evidence"]["funnel"])
        r = fu["rates"]
        return _Plan(
            f"در این بازه: انصراف پیش از پرداخت {_pct(r['no_attempt_rate'])}، رهاشدن در بانک {_pct(r['inbank_abandon_rate'])}، "
            f"خطای صریح بانکی {_pct(r['failed_bank_rate'])}. نرخ تبدیل نهایی {_pct(r['conv'])}. "
            "این سه حالت ماهیت متفاوتی دارند و در قیف پرداخت جدا نمایش داده می‌شوند.", "friction", refs, "high")

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

    # PSP / gateway routing — the engine already computes this card but nothing routed to it (ZB-008)
    if re.search(r"(درگاه|psp|گیت‌?وی|روتینگ|مسیردهی)", ql, re.IGNORECASE):
        g = peer_group(m)
        ctx = _Ctx(m=m, f=f, t=t, me=_period_agg_for(m, f, t), g=g, peers_rates=[],
                   tickets=_period_tickets(m, f, t))
        card = _card_psp_friction(ctx)
        if not card:
            return _Plan("در این بازه اختلاف معناداری بین درگاه‌های بانکی شما دیده نمی‌شود (یا حجم تلاش‌ها برای مقایسه کافی نیست).",
                         "psp", refs, "medium")
        refs.extend(card["evidence"][:1])
        return _Plan(card["observation_fa"] + " " + card["action_fa"], "psp", refs, card["confidence"])

    if re.search(r"(چه کار|چیکار|تمرکز|اولویت|این هفته|پیشنهاد|توصیه|فرصت|مهم‌ترین|بالا ببرم|بهتر کنم|افزایش|رشد بدم|بیشتر کنم)", ql):
        cards = generate(m, f, t)[:3]
        for c in cards:
            refs.extend(c["evidence"][:1])
        if not cards:
            return _Plan("در این بازه هیچ فرصت قابل اتکایی با شواهد کافی پیدا نشد — این یعنی وضعیت شما به همتایان نزدیک است.", "priorities", refs, "medium")
        # one shared formatter: the copilot used to print transaction counts as rial (ZB-013)
        lines = [f"{fa_num(i+1)}) {c['title_fa']} — {c['impact_label_fa']}"
                 + (f": {format_impact(c)}" if c["impact_high"] else "")
                 for i, c in enumerate(cards)]
        return _Plan("سه اولویت اول شما بر اساس اثر × اطمینان ÷ زحمت: " + " | ".join(lines) + ". جزئیات و شواهد در صفحه اصلی.", "priorities", refs, "high")

    # Nothing matched. If the question is not even about the payment business, say so plainly
    # instead of answering a different question with a confident summary (ZB-032/ZB-040).
    if not re.search(_BUSINESS, ql):
        return _Plan("این پرسش خارج از چیزی است که از داده پرداخت‌های شما قابل محاسبه است. " + _SCOPE_HINT,
                     "out_of_scope", refs, "low")

    ov = overview(m, f, t, None, None)
    refs.append(ov["evidence"]["gmv"])
    k = ov["kpis"]
    return _Plan(
        f"پرسش شما را دقیق متوجه نشدم، اما خلاصه این بازه: فروش موفق {_rial(k['gmv'])} از {fa_num(k['verified'])} پرداخت، "
        f"نرخ تبدیل {_pct(k['conv'])}، {fa_num(k['customers'])} مشتری. " + _SCOPE_HINT,
        "fallback", refs, "low")


def _period_agg_for(m: str, f: str, t: str) -> dict:
    from .analytics import period_agg
    me = period_agg(m, f, t)
    me["m"] = m
    return me


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
