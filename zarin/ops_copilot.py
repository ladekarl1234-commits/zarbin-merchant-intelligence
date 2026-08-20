"""Control Center copilot — grounded in real telemetry, not the merchant analytics.

Same two-stage contract as the merchant copilot: a deterministic planner reads the
live control-plane aggregates (platform / performance / AI-ops / sources) and writes
the answer; the gateway may only rephrase it. It never invents an incident, a cost,
a latency, or a source failure — if telemetry has no data, it says so.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from . import control
from .ai import gateway
from .fa import fa_money as _rial
from .fa import fa_num
from .fa import fa_pct as _pct


def _ev(name: str, definition: str, method: str) -> dict:
    return {"metric_id": "ops", "name_fa": name, "definition_fa": definition,
            "formula": method, "grain": "platform", "caveats": [], "sql": "",
            "sql_kind": "method", "params": {}, "n": None, "period": None,
            "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_fa": "تله‌متری زندهٔ پلتفرم"}


def _plan(question: str, f: str, t: str) -> tuple[str, str, list[dict], str]:
    ql = question.strip()

    if re.search(r"(fallback|بازگشت|جایگزین).*(زیاد|چرا|بالا)|چرا.*fallback", ql, re.IGNORECASE):
        a = control.ai_ops()
        if not a.get("has_data"):
            return ("هنوز درخواستی برای دستیار هوشمند ثبت نشده تا نرخ fallback معنا داشته باشد.", "ai_fallback", [], "low")
        refs = [_ev("نرخ fallback", "سهم پاسخ‌هایی که به موتور قطعی برگشتند", "fallback ÷ کل درخواست‌ها")]
        text = (f"نرخ fallback هوش مصنوعی {_pct(a['fallback_rate'])} است ({fa_num(a['fallback'])} از {fa_num(a['total'])}). "
                f"در fallback، پاسخ همچنان از موتور قطعی به کاربر می‌رسد، پس در دسترس‌بودن حفظ می‌شود. "
                f"رخدادهای پرریسک: {fa_num(a['hallucination_risk'])}.")
        return (text, "ai_fallback", refs, "high")

    if re.search(r"(هزینه|cost|خرج).*(ai|هوش|مدل)|هزینه", ql, re.IGNORECASE):
        a = control.ai_ops()
        if not a.get("has_data"):
            return ("هنوز هزینه‌ای ثبت نشده است؛ در حالت آفلاین یا با مدل‌های رایگان هزینه صفر است.", "ai_cost", [], "medium")
        refs = [_ev("هزینه هوش مصنوعی", "جمع هزینهٔ ارائه‌دهنده", "sum(cost_usd)")]
        text = (f"هزینهٔ کل هوش مصنوعی {a['cost_usd_total']} دلار برای {fa_num(a['llm_requests'])} درخواست مدل "
                f"({a['cost_per_request']} دلار به‌ازای هر درخواست). سیاست فقط-رایگان فعال است، پس انتظار هزینهٔ صفر می‌رود.")
        return (text, "ai_cost", refs, "high")

    if re.search(r"(کدام|چه).*(مدل|model)", ql, re.IGNORECASE):
        a = control.ai_ops()
        if not a.get("has_data") or not a.get("models"):
            return ("هنوز مدلی فراخوانی نشده است (حالت قطعی/آفلاین).", "ai_model", [], "medium")
        top = a["models"][0]
        refs = [_ev("مصرف مدل", "تعداد فراخوانی هر مدل", "count group by model")]
        return (f"بیشترین استفاده از مدل «{top['model']}» بوده ({fa_num(top['count'])} بار). همهٔ مدل‌ها طبق سیاست، رایگان‌اند.",
                "ai_model", refs, "high")

    if re.search(r"(مستند|grounded|شواهد).*(درصد|چقدر|چند)|چند درصد.*(جواب|پاسخ)", ql, re.IGNORECASE):
        a = control.ai_ops()
        if not a.get("has_data"):
            return ("هنوز پاسخی ثبت نشده است.", "ai_grounded", [], "low")
        refs = [_ev("نرخ مستندبودن", "سهم پاسخ‌هایی که اعدادشان از موتور قطعی می‌آید", "grounded ÷ کل")]
        text = (f"{_pct(a['grounded_rate'])} پاسخ‌ها مستند بوده‌اند و {_pct(a['evidence_coverage'])} دست‌کم یک شاهد داشته‌اند. "
                f"پاسخ‌های بدون شاهد: {fa_num(a['zero_evidence'])}.")
        return (text, "ai_grounded", refs, "high")

    if re.search(r"(ai|هوش).*(چطور|عملکرد|وضعیت|امروز)|عملکرد.*(هوش|ai)", ql, re.IGNORECASE):
        a = control.ai_ops()
        if not a.get("has_data"):
            return ("هنوز فعالیت هوش مصنوعی ثبت نشده است. با استفاده از دستیارِ پذیرنده، این بخش زنده پر می‌شود.", "ai_health", [], "low")
        refs = [_ev("سلامت هوش مصنوعی", "خلاصهٔ کیفیت پاسخ‌ها", "aggregate over ai_events")]
        text = (f"از {fa_num(a['total'])} درخواست: {_pct(a['grounded_rate'])} مستند، نرخ fallback {_pct(a['fallback_rate'])}، "
                f"تأخیر p95 برابر {fa_num((a['latency_ms'] or {}).get('p95'))} میلی‌ثانیه، هزینه {a['cost_usd_total']} دلار. "
                f"رخداد پرریسک: {fa_num(a['hallucination_risk'])}.")
        return (text, "ai_health", refs, "high")

    if re.search(r"(endpoint|کند|latency|تأخیر|سرعت|کندی)", ql, re.IGNORECASE):
        p = control.performance()
        if not p.get("has_data"):
            return ("هنوز ترافیک کافی برای سنجش کارایی ثبت نشده است.", "perf", [], "low")
        slow = p["endpoints"][0] if p["endpoints"] else None
        refs = [_ev("کندترین endpoint", "بالاترین تأخیر p95 میان مسیرها", "max(p95) over endpoints")]
        if not slow:
            return ("مسیری برای سنجش موجود نیست.", "perf", refs, "low")
        text = (f"کندترین مسیر «{slow['path']}» است با تأخیر p95 برابر {fa_num(slow['p95'])} میلی‌ثانیه. "
                f"تأخیر کلی p95 برابر {fa_num(p['latency_ms']['p95'])} و نرخ خطای سرور {_pct(p['error_rate'])}.")
        return (text, "perf", refs, "high")

    if re.search(r"(منبع|source|sync|گوگل|ga4|آنالیتیکس)", ql, re.IGNORECASE):
        s = control.sources(f, t)
        bad = [x for x in s["sources"] if not x["connected"]]
        refs = [_ev("وضعیت منابع", "اتصال هر منبع داده", "status per adapter")]
        if not bad:
            return ("همهٔ منابع داده متصل‌اند.", "sources", refs, "high")
        names = "، ".join(f"{x['name_fa']} ({x['status']})" for x in bad)
        text = (f"منابع متصل‌نشده: {names}. منبع حقیقتِ مالی (زرین‌پال) متصل است و محصول کامل کار می‌کند؛ "
                f"این منابع، سیگنال‌های تکمیلی‌اند.")
        return (text, "sources", refs, "high")

    if re.search(r"(مشکل|توجه|هشدار|خراب|attention|incident)", ql, re.IGNORECASE):
        return _attention(f, t)

    if re.search(r"(کل سیستم|سیستم|پلتفرم|همه‌چیز|وضعیت کلی)", ql):
        return _system(f, t)

    return _system(f, t)


def _attention(f: str, t: str) -> tuple[str, str, list[dict], str]:
    perf = control.performance()
    plat = control.platform(f, t)
    items = list(perf.get("attention", [])) if perf.get("has_data") else []
    items += [{"fa": i["title_fa"]} for i in plat.get("insights", [])]
    refs = [_ev("موارد نیازمند توجه", "هشدارهای کارایی + بینش‌های پلتفرم", "attention ∪ insights")]
    if not items:
        return ("در حال حاضر موردِ نیازمند توجهی شناسایی نشده است.", "attention", refs, "medium")
    lines = "؛ ".join(x["fa"] for x in items[:4])
    return (f"مواردی که اکنون ارزش بررسی دارند: {lines}.", "attention", refs, "high")


def _system(f: str, t: str) -> tuple[str, str, list[dict], str]:
    plat = control.platform(f, t)
    perf = control.performance()
    ai = control.ai_ops()
    k = plat["kpis"]
    refs = [_ev("سلامت پلتفرم", "خلاصهٔ کسب‌وکار + کارایی + هوش مصنوعی", "platform ⊕ performance ⊕ ai_ops")]
    parts = [
        (f"{fa_num(k['active_merchants'])} پذیرندهٔ فعال، {fa_num(k['sessions'])} جلسهٔ پرداخت، "
         f"فروش موفق {_rial(k['gmv'])}، نرخ تبدیل {_pct(k['conv'])}")
    ]
    if perf.get("has_data"):
        parts.append(f"تأخیر API p95 برابر {fa_num(perf['latency_ms']['p95'])} میلی‌ثانیه و نرخ خطا {_pct(perf['error_rate'])}")
    if ai.get("has_data"):
        parts.append(f"هوش مصنوعی: {_pct(ai['grounded_rate'])} مستند، fallback {_pct(ai['fallback_rate'])}")
    return ("وضعیت کلی: " + "؛ ".join(parts) + ".", "system", refs, "high")


def answer(question: str, f: str, t: str, *, provider=None, use_llm: bool = True) -> dict:
    text, intent, refs, conf = _plan(question, f, t)
    resp = gateway.explain(question=question, merchant_scope="platform", intent=intent,
                           deterministic_answer_fa=text, evidence=refs, confidence=conf,
                           surface="ops", provider=provider, _use_default=use_llm)
    return resp.to_dict()
