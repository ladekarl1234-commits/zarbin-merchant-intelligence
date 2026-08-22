"""Grounded Persian business copilot.

Deterministic-first, in three stages:

  question → _route()  : out-of-scope families → exact rules → semantic retrieval (nlu.py)
           → _ANSWER[] : the deterministic Persian answer + traceable evidence
           → gateway.explain() : OPTIONAL LLM rephrasing, grounding-guarded

Every number is produced by the deterministic analytics engine. The LLM, when a key is
present, may only make the wording friendlier — a grounding guard rejects any answer that
introduces an unsupported number, so the copilot works identically (and correctly) with
zero keys and zero network.

Routing used to be a ladder of regexes with a single terminal `else`: a question no
pattern matched got a generic business summary. That is a *silent* retrieval failure —
the merchant is answered, but not about what they asked. The rules are still first,
because they are exact and they encode the orderings the product cares about; what
follows them is now retrieval (`zarin/nlu.py`) with a score, so an unmatched question
lands in one of three honest outcomes — routed, asked back, or declined — instead of
being answered with something else.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

from . import nlu
from .ai import gateway
from .ai.provider import AIProvider
from .analytics import changes, customers, funnel, overview
from .config import FEE_CAVEAT, MIN_SEGMENT_N, PREFERRED_PEERS
from .fa import fa_money as _rial
from .fa import fa_num
from .fa import fa_pct as _pct
from .insights import _card_psp_friction, _Ctx, _period_tickets, format_impact, generate
from .peers import benchmarks, peer_group
from .registry import evidence

FA_METRIC = {"conv": "نرخ تبدیل", "first_try_conv": "موفقیت در اولین تلاش",
             "no_attempt_rate": "انصراف پیش از پرداخت", "inbank_abandon_rate": "رهاشدن در بانک",
             "recovery_rate": "بازیابی پس از شکست"}


class _Plan:
    __slots__ = ("confidence", "intent", "refs", "suggestions", "text")

    def __init__(self, text: str, intent: str, refs: list[dict], confidence: str = "medium",
                 suggestions: list[str] | None = None):
        self.text, self.intent, self.refs, self.confidence = text, intent, refs, confidence
        self.suggestions = suggestions or []


# --- stage 1: questions the engine genuinely cannot answer ------------------------------
# Saying so is the correct behaviour — answering a DIFFERENT question with a confident
# business summary is what the audit flagged (ZB-032/ZB-040). These run BEFORE the intent
# rules and before retrieval, because a question can be perfectly on-vocabulary and still
# be unanswerable: «نرخ تبدیل من در کمپین نوروز سال بعد چقدر ثبت شده؟» is a conversion
# question about a period that does not exist.
#
# Every family here is a *safety* control, and each one closed a measured failure on the
# routing evaluation set: without them the router answered 7 of 25 out-of-scope questions
# with real numbers.
_OUT_OF_SCOPE = (
    # Future. A forecast dressed as history is still a forecast — the second alternation
    # is what catches «سال بعد» / «تا آخر امسال» inside an otherwise past-tense sentence.
    ((r"(فردا|هفته آینده|ماه آینده|سال آینده|پیش.?بینی|پیش.?بین|چقدر می.?شود|خواهد شد)"
      r"|(سال بعد|سال دیگ|ماه بعد|هفته بعد|تا آخر امسال|تا پایان امسال|تا پایان سال)"
      # «سه ماه دیگه»، «چند وقت دیگه»، «۲ هفته دیگر» — a horizon expressed as a distance
      r"|((چند|یک|دو|سه|چهار|پنج|شش|\d+) ?(ماه|هفته|روز|سال) ?دیگ)|چند وقت دیگ"
      r"|(به دست می.?آورم|به دست میارم|خواهم داشت|قراره چقدر|قراره چند|چقدر می.?پره بالا)"), "forecast"),
    ((r"(نرخ ارز|قیمت دلار|دلار چند|قیمت یورو|قیمت طلا|طلا چند|قیمت سکه"
      r"|بورس|شاخص کل|سهام|بیت.?کوین|ارز دیجیتال|رمزارز)"), "external_market"),
    ((r"(شماره کارت|شماره تماس|شماره موبایل|کد ملی|ایمیل|آدرس|نام مشتری|اسم مشتری"
      r"|نام و نام خانوادگی|لیست مشتری|اطلاعات شخصی|هویت مشتری|چهار رقم آخر)"
      # "give me their number so I can call them" — the identifier is never named, but the
      # request is unmistakable.
      r"|((شماره|شمارش|شماره.?اش|تلفن|موبایل).{0,15}(بده|بفرست|بگو|برام))|زنگ بزنم"), "pii"),
    # Instruction override / raw-data exfiltration. The copilot never runs model-authored
    # SQL and never returns rows, so a request to do either is refused at the router rather
    # than relied on to fail downstream. (Defence in depth: ai/safe_context.assert_safe()
    # is what guarantees the model never SEES rows, SQL or ids in the first place.)
    ((r"(?i)(نادیده بگیر|فراموش کن|بدون محدودیت|بی.?محدودیت|محدودیت.{0,12}(بردار|نداری)"
      r"|دستورالعمل|system ?prompt|jailbreak|ignore .{0,20}instruction"
      r"|کوئری|query خام|sql|جدول کاربر|دیتابیس|پایگاه داده|رمز عبور|توکن|api key"
      r"|حالت دولوپر|developer mode|فیلتر.{0,12}(خاموش|بردار|غیرفعال)|بدون فیلتر|سانسور"
      r"|پرامپت سیستم|دسترسی کامل|پذیرنده.?های دیگ|سایر پذیرندگان)"), "injection"),
    # Real business questions about data this product does not hold. Answering them from
    # payment rows would be invention. NOTE: the bare word «تبلیغات» is deliberately absent
    # — «آیا تبلیغات باعث افت فروش شد؟» is a sales-change question with an unverifiable
    # hypothesis attached, and the right answer is the decomposition without the hypothesis.
    ((r"(?i)(اینستاگرام|instagram|گوگل ادز|google ?ads|ادوردز|سئو|seo|هزینه هر کلیک|cpc|ctr"
      r"|ایمپرشن|بازدید سایت|ترافیک سایت|وارد سایت|بازدیدکننده|نرخ پرش|bounce"
      r"|حقوق|دستمزد|بیمه|کارمند|پرسنل|مالیات|اجاره"
      r"|انبار|موجودی کالا|موجودی محصول|سفارش کالا|تامین.?کننده)"), "not_in_dataset"),
    (r"^\s*(سلام|درود|خداحافظ|ممنون|مرسی|تشکر|چطوری|خوبی)\W*$", "greeting"),
)
_SCOPE_HINT = ("می‌توانم دربارهٔ فروش موفق، مسیر پرداخت و دلیل شکست‌ها، مقایسه با کسب‌وکارهای مشابه، "
               "مشتریان و بازگشتشان، تلاش مجدد، درگاه‌های بانکی و اولویت‌های این هفته پاسخ بدهم.")


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


# --- stage 2: exact rules ------------------------------------------------------------
# Ordered, high-precision, and the only thing allowed to decide a question the product has
# a strong opinion about. Two examples that a similarity score would get wrong:
#   * recovery BEFORE friction — «چقدر از تراکنش‌های ناموفق نجات پیدا کرد؟» contains a
#     failure word and a retry word; it is a recovery question.
#   * psp AFTER friction — «چرا پرداخت در درگاه شکست می‌خورد؟» is about the funnel, not
#     about choosing a gateway.
# Each pattern is tried against the raw question first (exactly the behaviour these rules
# had before retrieval existed, so nothing regresses), then against the normalised form,
# which folds Arabic ك/ي, ZWNJ and diacritics — «تاييدنشده» and «تایید‌نشده» reach the same
# rule without enumerating spellings.
_RULES: tuple[tuple[str, str], ...] = (
    # WHICH-gateway comes first: «کدوم درگاه بیشترین خطای بانکی رو ساخته؟» carries a failure
    # word (friction) and an hour range may carry a time word (hours), but a question that
    # asks the product to *choose between rails* is a psp question whatever else it mentions.
    ("psp", (r"(?i)(کدام|کدوم|کدومشون|کدام.?یک|بهترین|بدترین|ضعیف.?ترین)"
             r".{0,40}(درگاه|psp|گیت.?وی|gateway|بانک|رِ?یل)"
             # Persian puts the interrogative on either side: «کدوم درگاه ...» and
             # «بین بانک‌هایی که ... کدومشون ...» are the same question.
             r"|(درگاه|psp|گیت.?وی|gateway|بانک).{0,40}(کدام|کدوم|کدومشون|کدام.?یک)")),
    # Rank-among-peers beats every metric word it may contain: «رتبه من در نرخ نجات بین
    # کسب‌وکارهای مشابه» is a benchmarking question, not a recovery question.
    ("peers", (r"(رتبه|جایگاه|صدک|مقایسه|بنچمارک|بهتر|بدتر|جلوتر|عقب.?تر)"
               r".{0,40}(همتا|مشابه|رقیب|رقبا|هم.?رده|هم.?اندازه|هم.?صنف|کسب.?و.?کار|بقیه|بازار|صنعت)")),
    ("changes", (r"(چرا|علت|دلیل|بخاطر|به خاطر).*(کم|افت|پایین|نزول|خراب|ریخت|سقوط|کاهش|ضعیف"
                 r"|بالا رفت|رشد|زیاد شد|بیشتر شد|یهو)|افت.*(فروش|درآمد)")),
    ("hours", r"(کی|چه ساعت|چه زمان|ساعت).*(خرید|فروش|پرداخت)"),
    # recovery is matched BEFORE friction (see above). Persian puts the retry word on either
    # side of the verb, so both orders are listed rather than relying on one.
    ("recovery", (r"(?i)(تلاش مجدد|تلاش دوباره|دوباره تلاش|دوباره امتحان|دوباره پرداخت"
                  r"|دوباره زد|بار دوم|دفعه دوم|بازیابی|نجات|ریکاوری|retry)"
                  r"|(بار اول|دفعه اول).{0,40}(دوباره|مجدد|بعد)")),
    # Ticket-size comparison beats the generic drop-off rule: «سفارش‌های گران‌قیمت بیشتر
    # می‌پرند یا خریدهای کوچک؟» is a question about amount bands that happens to use a
    # drop-off verb.
    ("amount_bands", (r"(گران|گرون|ارزان|ارزون|کم.?مبلغ|پرمبلغ|کوچیک|کوچک|بزرگ|سنگین)"
                      r".{0,30}(موفق|تبدیل|شکست|پرداخت|می.?پر|جواب|ناموفق|ول می)"
                      # «بازه قیمتی» / «محدوده مبلغی» — the band itself is the subject, so
                      # this must beat friction even when the verb is a drop-off verb.
                      r"|(بازه|دامنه|محدوده).{0,12}(مبلغ|قیمت|ریال|تومن|تومان)"
                      r"|(بالای|زیر|بیش از|کمتر از).{0,15}(تومن|تومان|ریال|میلیون|هزار)")),
    ("friction", (r"(?i)(پرداخت|درگاه|تراکنش).*(شکست|خطا|ناموفق|رد شد|fail)"
                  r"|(شکست|خطا|ناموفق|fail).*(بیشتر|بدتر|زیاد|پرداخت|درگاه|بانک|تراکنش)"
                  r"|چرا.*(شکست|خطا|ناموفق|fail)|وضعیت (شکست|خطا)"
                  r"|(کجا|کجای).{0,25}(مسیر|قیف|پرداخت|درگاه|بانک|می.?پر)"
                  r"|(رها می|ول می|بی.?خیال می|منصرف|ریزش|می.?پرن)")),
    ("peers", r"(مقایسه|همتا|رقبا|رقیب|مشابه|جایگاه|رتبه|بنچمارک)"),
    # Dormancy is a customer-base question, not a return-behaviour one — «مشتریای خوابیده که
    # دیگه خرید نمی‌کنن» used to land in `repeat` and get a repeat-purchase answer.
    ("customers", (r"(خفته|خوابیده|غیرفعال|دیگر خرید نمی|دیگه خرید نمی|دیگه نمی.?آ|از دست داده"
                   r"|برنگشت|سراغ.{0,10}نیامد|سراغ.{0,10}نیومد|هیچ خریدی نکرد|خریدی نکرده)")),
    ("repeat", r"مشتری.*(برگشت|تکرار|وفادار)|(تکراری|بازگشت).*(مشتری)"),
    ("psp", r"(?i)(درگاه|psp|گیت‌?وی|gateway|روتینگ|مسیردهی)"),
    # New in the retrieval pass: five intents the engine could already compute but nothing
    # routed to, so every one of these questions used to return the generic summary.
    ("paid_unverified", r"(?i)(تایید ?نشده|تاییدنشده|verify ?نشده|وریفای ?نشده|بلاتکلیف|منتظر تایید)"),
    ("fee", r"(کارمزد|کمیسیون)"),
    ("amount_bands", (r"(بازه|دامنه).*(مبلغ|قیمت)|(مبلغ|قیمت).*(بازه|دامنه)"
                      r"|(گران|ارزان|کم.?مبلغ|پرمبلغ).*(موفق|تبدیل|شکست|پرداخت)")),
    ("priorities", (r"(چه کار|چیکار|تمرکز|اولویت|پیشنهاد|توصیه|فرصت|مهم.?ترین"
                    r"|بالا ببرم|بهتر کنم|افزایش|رشد بدم|بیشتر کنم|راهکار"
                    # «این هفته» alone used to be enough, so «چرا فروشم این هفته ریخت؟»
                    # was answered with a priority list instead of the decline decomposition.
                    r"|این هفته.{0,20}(تمرکز|کار|اقدام|انجام))")),
)
_RULES_C = tuple((intent, re.compile(p)) for intent, p in _RULES)


def _rule_intent(question: str) -> str | None:
    """First rule, in listed order, that matches the question in EITHER spelling.

    The loops are nested rule-outer / spelling-inner on purpose. Testing every rule
    against the raw text first would let a low-priority rule that happens to match the
    raw spelling beat a high-priority rule that only matches after folding: «مشتريا كجا
    ميپرن؟ قبل از درگاه...» (Arabic ك/ي) hit the psp rule on the raw text because
    «درگاه» is spelled Persian, while the friction rule that owns it needed the folded
    «كجا»→«کجا». Rule priority is the contract; spelling is not.
    """
    normalised = nlu.normalize(question)
    for _intent, pattern in _RULES_C:
        if pattern.search(question) or pattern.search(normalised):
            return _intent
    return None


# --- stage 3: answers ------------------------------------------------------------------
# One function per intent. Every one returns a _Plan whose numbers come from the analytics
# engine and whose refs are registry evidence — the same contract the dashboard cards have.


def _ans_changes(m, f, t, q=''):
    refs: list[dict] = []
    halves = _equal_halves(f, t)
    if not halves:
        return _Plan("بازه انتخابی برای مقایسه دو نیمه کوتاه است (حداقل ۲۸ روز لازم است).",
                     "changes", refs, "low")
    a_end, b_start, half = halves
    ch = changes(m, f, a_end, b_start, t)
    refs.append(ch["evidence"])
    if not ch["decomposable"]:
        return _Plan("در این بازه داده کافی برای تجزیه تغییر فروش وجود ندارد "
                     "(یکی از دوره‌ها فروش موفق ثبت‌شده ندارد).", "changes", refs, "low")
    c = ch["contrib"]
    names = {"sessions": "تعداد جلسه‌ها", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط"}
    parts = "، ".join(f"{names[k]}: {_rial(c[k])}" for k in c)
    trend = "افت" if ch["delta_gmv"] < 0 else "رشد"
    # The merchant asked why sales FELL and they did not: correct the premise before
    # answering it. Reporting «رشد داشت» under a «چرا کم شد؟» question, with no
    # acknowledgement, reads as if the engine misunderstood.
    premise = ""
    if ch["delta_gmv"] > 0 and re.search(r"(کم|افت|پایین|نزول|خراب|ریخت|سقوط|کاهش|ضعیف)", q or ""):
        premise = "فروش شما در این بازه کم نشده است. "
    return _Plan(
        premise
        + f"بین دو نیمهٔ {fa_num(half)} روزهٔ این بازه، فروش موفق {_rial(abs(ch['delta_gmv']))} {trend} داشت. "
        f"سهم هر عامل: {parts}. "
        f"بزرگ‌ترین عامل: «{names[max(c, key=lambda k: abs(c[k]))]}». "
        "جزئیات در صفحه «چه چیزی تغییر کرد؟».", "changes", refs, "high")


def _ans_hours(m, f, t, q=''):
    refs: list[dict] = []
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


def _ans_recovery(m, f, t, q=''):
    refs: list[dict] = []
    fu = funnel(m, f, t)
    refs.append(fu["evidence"]["recovery"])
    rec = fu["recovery"]
    return _Plan(
        f"از {fa_num(rec['first_fail_pool'])} جلسه‌ای که تلاش اولشان ناموفق بود، "
        f"{fa_num(rec['recovered'])} جلسه با تلاش مجدد موفق شد "
        f"({_pct(rec['recovery_rate'])}) و {_rial(rec['recovered_gmv'])} فروش نجات یافت.",
        "recovery", refs, "high")


def _ans_friction(m, f, t, q=''):
    refs: list[dict] = []
    fu = funnel(m, f, t)
    refs.append(fu["evidence"]["funnel"])
    r = fu["rates"]
    return _Plan(
        f"در این بازه: انصراف پیش از پرداخت {_pct(r['no_attempt_rate'])}، "
        f"رهاشدن در بانک {_pct(r['inbank_abandon_rate'])}، "
        f"خطای صریح بانکی {_pct(r['failed_bank_rate'])}. نرخ تبدیل نهایی {_pct(r['conv'])}. "
        "این سه حالت ماهیت متفاوتی دارند و در قیف پرداخت جدا نمایش داده می‌شوند.",
        "friction", refs, "high")


def _ans_peers(m, f, t, q=''):
    refs: list[dict] = []
    b = benchmarks(m, f, t)
    refs.append(b["evidence"])
    if not b["group"]["sufficient"]:
        return _Plan("تعداد پذیرندگان قابل مقایسه برای ساخت معیار همتایان کافی نیست؛ "
                     "به جای عدد نامطمئن، این مقایسه نمایش داده نمی‌شود.", "peers", refs, "low")
    rows = [r for r in b["rows"] if not r["suppressed"]]
    txt = "؛ ".join(f"{FA_METRIC[r['metric']]}: صدک {fa_num(r['percentile'])} از {fa_num(r['n_peers'])} همتا"
                    for r in rows[:3])
    # A percentile over 5 peers moves in 20-point steps. Quoting it like a percentile over
    # 200 is the kind of false precision this product exists to avoid.
    thin = any(r.get("low_n") for r in rows[:3]) or b["group"]["n"] < PREFERRED_PEERS
    caveat = (" گروه همتایان کوچک است، بنابراین صدک تقریبی است و به تغییر یک همتا حساس است."
              if thin else "")
    return _Plan(f"گروه همتایان شما: {b['group']['rule_fa']} ({fa_num(b['group']['n'])} پذیرنده). {txt}."
                 + caveat + " جزئیات و دلیل انتخاب همتایان در صفحه «همتایان».",
                 "peers", refs, "medium" if thin else "high")


def _ans_repeat(m, f, t, q=''):
    refs: list[dict] = []
    cu = customers(m, f, t)
    refs.append(cu["evidence"]["repeat"])
    s = cu["summary"]
    if not s["customers"]:
        return _Plan("در این بازه مشتری پرداخت موفقی ثبت نشده است.", "repeat", refs, "low")
    share = s["repeat_txns"] / s["txns"] if s["txns"] else None
    gshare = s["repeat_gmv"] / s["gmv"] if s["gmv"] else None
    return _Plan(
        f"{fa_num(s['customers'])} مشتری در این بازه پرداخت موفق داشتند "
        f"({fa_num(s['new_customers'])} مشتری جدید). "
        f"مشتریان تکراری {_pct(share)} از تراکنش‌ها و {_pct(gshare)} از فروش را ساخته‌اند. "
        "(تحلیل مشتری فقط پرداخت‌کنندگان موفق همین پذیرنده را می‌بیند.)", "repeat", refs, "medium")


def _ans_customers(m, f, t, q=''):
    """Customer base: size, newness, concentration, dormancy — distinct from `repeat`,
    which is about return behaviour. Nothing routed here before; the question came back
    as a generic summary."""
    refs: list[dict] = []
    cu = customers(m, f, t)
    refs.append(cu["evidence"]["customers"])
    s, conc, dorm = cu["summary"], cu["concentration"], cu["dormant"]
    if not s["customers"]:
        return _Plan("در این بازه مشتری پرداخت موفقی ثبت نشده است.", "customers", refs, "low")
    # "new" = first-ever purchase inside the window. Over the full data range that is
    # everyone, and printing «۲۳٬۸۰۱ از ۲۳٬۸۰۱ نفر جدید بودند» reads like a bug rather than
    # a window artefact — so say which it is.
    if s["new_customers"] >= s["customers"]:
        head = (f"{fa_num(s['customers'])} مشتری در این بازه پرداخت موفق داشتند و همگی اولین "
                "خرید موفقشان در همین بازه بوده است (بازه، کل تاریخچهٔ داده را پوشش می‌دهد)")
    else:
        head = (f"{fa_num(s['customers'])} مشتری در این بازه پرداخت موفق داشتند و "
                f"{fa_num(s['new_customers'])} نفر از آن‌ها برای اولین بار خرید کردند")
    parts = [head]
    if conc.get("top5_share") is not None:
        refs.append(cu["evidence"]["concentration"])
        parts.append(f"سهم پنج مشتری برتر از فروش موفق {_pct(conc['top5_share'])} است")
    if dorm.get("n"):
        # EXACT definition (analytics.customers): >=3 successful payments, and no purchase
        # in the 30 days before the window end. An earlier wording said "in the second half
        # of the period", which is a different set entirely.
        parts.append(f"{fa_num(dorm['n'])} مشتری وفادار (دست‌کم سه خرید موفق) بیش از ۳۰ روز است "
                     f"خریدی نکرده‌اند و مجموع خرید قبلی‌شان {_rial(dorm['gmv'])} بوده است")
    return _Plan("؛ ".join(parts) + ". (تحلیل مشتری فقط پرداخت‌کنندگان موفق همین پذیرنده را می‌بیند.)",
                 "customers", refs, "medium" if s["customers"] >= 50 else "low")


def _ans_psp(m, f, t, q=''):
    refs: list[dict] = []
    g = peer_group(m)
    ctx = _Ctx(m=m, f=f, t=t, me=_period_agg_for(m, f, t), g=g, peers_rates=[],
               tickets=_period_tickets(m, f, t))
    card = _card_psp_friction(ctx)
    if not card:
        return _Plan("در این بازه اختلاف معناداری بین درگاه‌های بانکی شما دیده نمی‌شود "
                     "(یا حجم تلاش‌ها برای مقایسه کافی نیست).", "psp", refs, "medium")
    refs.extend(card["evidence"][:1])
    return _Plan(card["observation_fa"] + " " + card["action_fa"], "psp", refs, card["confidence"])


def _ans_priorities(m, f, t, q=''):
    refs: list[dict] = []
    cards = generate(m, f, t)[:3]
    for c in cards:
        refs.extend(c["evidence"][:1])
    if not cards:
        return _Plan("در این بازه هیچ فرصت قابل اتکایی با شواهد کافی پیدا نشد — "
                     "این یعنی وضعیت شما به همتایان نزدیک است.", "priorities", refs, "medium")
    # one shared formatter: the copilot used to print transaction counts as rial (ZB-013)
    lines = [f"{fa_num(i+1)}) {c['title_fa']} — {c['impact_label_fa']}"
             + (f": {format_impact(c)}" if c["impact_high"] else "")
             for i, c in enumerate(cards)]
    return _Plan("سه اولویت اول شما بر اساس اثر × اطمینان ÷ زحمت: " + " | ".join(lines)
                 + ". جزئیات و شواهد در صفحه اصلی.", "priorities", refs, "high")


def _ans_gmv(m, f, t, q=''):
    """The plain KPI question. This is what `fallback` used to answer as a consolation
    prize for every unrecognised question; it is now a first-class intent with high
    confidence, and nothing else lands here by accident."""
    ov = overview(m, f, t, None, None)
    k = ov["kpis"]
    refs = [ov["evidence"]["gmv"], ov["evidence"]["conv"]]
    if not k["sessions"]:
        return _Plan("در این بازه هیچ جلسهٔ پرداختی ثبت نشده است.", "gmv", refs, "low")
    return _Plan(
        f"در این بازه {fa_num(k['sessions'])} جلسهٔ پرداخت ثبت شد و {fa_num(k['verified'])} "
        f"پرداخت به تایید رسید؛ فروش موفق {_rial(k['gmv'])} با نرخ تبدیل {_pct(k['conv'])}. "
        f"میانهٔ مبلغ هر پرداخت موفق {_rial(k['median_ticket'])} و "
        f"{fa_num(k['customers'])} مشتری پرداخت موفق داشتند.", "gmv", refs, "high")


def _ans_paid_unverified(m, f, t, q=''):
    """The product's headline finding, and until now unreachable from the copilot."""
    ov = overview(m, f, t, None, None)
    k = ov["kpis"]
    refs = [ov["evidence"]["paid_unverified"]]
    if not k["paid_unverified"]:
        return _Plan("در این بازه هیچ پرداخت تسویه‌شدهٔ تاییدنشده‌ای ثبت نشده است.",
                     "paid_unverified", refs, "medium")
    tail = ""
    if k["gmv"]:
        tail = f" این مبلغ معادل {_pct(k['paid_unverified_amount'] / k['gmv'])} فروش موفق همین بازه است."
    return _Plan(
        f"{fa_num(k['paid_unverified'])} جلسه در این بازه در بانک تسویه شده اما هرگز تایید نشده‌اند؛ "
        f"مجموع {_rial(k['paid_unverified_amount'])}. این پول واقعاً پرداخت شده است و برآورد نیست."
        + tail + " فهرست نمونه‌ها از دکمهٔ «محاسبه» قابل دیدن است.",
        "paid_unverified", refs, "high")


# Below this spread between the best and worst amount band there is no finding to report,
# only noise dressed as one — the same restraint the insight cards apply. Measured: M156's
# bands span 53.3%–55.9%, which a "best band / worst band" sentence would have sold as a
# result worth acting on.
_BAND_SPREAD_MIN = 0.05

_FEE_SQL = ("SELECT sum(adjusted_fee) FROM sessions\n"
            "WHERE merchant_key = $m AND d BETWEEN $f AND $t AND outcome = 'verified'")


def _ans_fee(m, f, t, q=''):
    ov = overview(m, f, t, None, None)
    k = ov["kpis"]
    ref = evidence("fee_index", sql=_FEE_SQL, params={"m": m, "f": f, "t": t},
                   n=int(k["verified"] or 0), period=f"{f} تا {t}")
    if not k["fee_index_sum"]:
        return _Plan("در این بازه شاخص کارمزدی برای پرداخت‌های موفق شما ثبت نشده است.",
                     "fee", [ref], "low")
    share = f" نسبت آن به فروش موفق {_pct(k['fee_index_sum'] / k['gmv'])} است." if k["gmv"] else ""
    return _Plan(
        f"شاخص نسبی کارمزد شما در این بازه {fa_num(k['fee_index_sum'])} است." + share
        + " " + FEE_CAVEAT, "fee", [ref], "medium")


def _ans_amount_bands(m, f, t, q=''):
    refs: list[dict] = []
    fu = funnel(m, f, t)
    refs.append(fu["evidence"]["amount_bands"])
    bands = [b for b in fu["amount_bands"] if b["sessions"] >= MIN_SEGMENT_N]
    if len(bands) < 2:
        return _Plan("تعداد جلسه‌ها در بازه‌های مبلغی برای مقایسهٔ قابل اتکا کافی نیست.",
                     "amount_bands", refs, "low")
    best = max(bands, key=lambda b: (b["conv"], -b["band"]))
    worst = min(bands, key=lambda b: (b["conv"], b["band"]))
    spread = (best["conv"] or 0) - (worst["conv"] or 0)
    if best["band"] == worst["band"] or spread < _BAND_SPREAD_MIN:
        return _Plan(
            ("اختلاف معناداری بین بازه‌های مبلغی دیده نمی‌شود: نرخ تبدیل از "
             f"{_pct(worst['conv'])} تا {_pct(best['conv'])} تغییر می‌کند "
             f"({fa_num(round(spread * 100))} واحد درصد)، که برای نتیجه‌گیری کافی نیست."),
            "amount_bands", refs, "low")
    return _Plan(
        f"بهترین نرخ تبدیل در بازهٔ {_rial(best['lo'])} تا {_rial(best['hi'])} است "
        f"({_pct(best['conv'])} از {fa_num(best['sessions'])} جلسه) و ضعیف‌ترین در بازهٔ "
        f"{_rial(worst['lo'])} تا {_rial(worst['hi'])} ({_pct(worst['conv'])} از "
        f"{fa_num(worst['sessions'])} جلسه). تفکیک کامل در صفحه «قیف پرداخت».",
        "amount_bands", refs, "high" if min(best["sessions"], worst["sessions"]) >= 500 else "medium")


_ANSWER = {
    "changes": _ans_changes, "hours": _ans_hours, "recovery": _ans_recovery,
    "friction": _ans_friction, "peers": _ans_peers, "repeat": _ans_repeat,
    "customers": _ans_customers, "psp": _ans_psp, "priorities": _ans_priorities,
    "gmv": _ans_gmv, "paid_unverified": _ans_paid_unverified, "fee": _ans_fee,
    "amount_bands": _ans_amount_bands,
}
assert set(_ANSWER) == set(nlu.BANK), "every retrievable intent needs an answer, and vice versa"


def _ans_out_of_scope() -> _Plan:
    return _Plan("این پرسش خارج از چیزی است که از داده پرداخت‌های شما قابل محاسبه است. " + _SCOPE_HINT,
                 "out_of_scope", [], "low")


def _ans_unrecognised(question: str) -> _Plan:
    """Nothing scored high enough, but no safety family fired either. Offer the nearest
    answerable questions rather than assert the question was out of bounds."""
    match = nlu.route(question.strip())
    options = "، ".join(f"«{s}»" for s in match.suggestions)
    return _Plan(f"پرسش شما را دقیق متوجه نشدم. این‌ها را می‌توانم با شواهد پاسخ بدهم: {options}",
                 "out_of_scope", [], "low", suggestions=list(match.suggestions))


def _ans_clarify(match: nlu.Match) -> _Plan:
    """On topic, but the router is not confident WHICH question. Naming the nearest
    answerable questions is strictly better than either guessing or shrugging — and it is
    the outcome the old single `else` branch had no way to express."""
    options = "، ".join(f"«{s}»" for s in match.suggestions)
    return _Plan("پرسش شما را با اطمینان کافی تشخیص ندادم. نزدیک‌ترین پرسش‌هایی که "
                 f"می‌توانم دقیق پاسخ بدهم: {options}", "clarify", [], "low",
                 suggestions=list(match.suggestions))


_OUT_OF_SCOPE_C = tuple((re.compile(p), kind) for p, kind in _OUT_OF_SCOPE)


# Clauses that explicitly EXCLUDE a topic. «نرخ تبدیلم رو ساعت‌به‌ساعت نمی‌خوام، همون عدد
# کلی رو بگو» names two topics and wants one of them; a bag-of-words router reads the
# excluded one as the loudest signal and answers it. Dropping the negated clause before
# routing is the smallest fix that generalises — it is not a list of question shapes.
_NEGATED_CLAUSE = re.compile(r"(نمی.?خوا|نمیخوا|لازم ندارم|کاری ندارم|ولش کن|فعلا ولش|بی.?خیالِ?\s)")
_CLAUSE_SPLIT = re.compile(r"[،؛,;]")


def _drop_negated_clauses(question: str) -> str:
    """Remove comma/semicolon-separated clauses that say a topic is NOT wanted.

    Returns the original when every clause is negated (nothing left to route on) or when
    the question has no clause boundary — never an empty string.
    """
    parts = _CLAUSE_SPLIT.split(question)
    if len(parts) < 2:
        return question
    kept = [p for p in parts if p.strip() and not _NEGATED_CLAUSE.search(p)]
    return "، ".join(kept) if kept else question


@lru_cache(maxsize=1024)
def route_detail(question: str) -> tuple[str, str]:
    """(intent, why). `why` is one of:

        refused:<family>  a safety family matched — forecast / market / pii / injection /
                          not_in_dataset / greeting. The engine cannot answer it and knows why.
        rule:<intent>     an exact rule matched.
        search            retrieval was confident enough to route.
        ambiguous         on topic, but the router could not tell which question (→ clarify).
        unknown           nothing scored high enough. NOT the same as `refused`: the engine
                          has no reason to believe the question is out of bounds, only that it
                          did not recognise it — so the answer offers alternatives instead of
                          asserting the question was illegitimate.

    Separated from `_plan` because it touches no database — which is what lets the
    evaluation in zarin/ai/eval/retrieval.py score 120 questions in milliseconds, and lets
    the tests assert rule priority without building marts. `_plan` and the eval therefore
    share ONE routing implementation rather than two that can drift.
    """
    ql = _drop_negated_clauses(question.strip()).strip() or question.strip()
    # stage 1: families the engine genuinely cannot answer. Saying so is the correct
    # behaviour — answering a DIFFERENT question with a confident business summary is
    # what the audit flagged (ZB-032/ZB-040). Checked against the normalised form too,
    # so «شماره كارت» (Arabic kaf) cannot slip past the PII family.
    normalised = nlu.normalize(ql)
    for pattern, kind in _OUT_OF_SCOPE_C:
        if pattern.search(ql) or pattern.search(normalised):
            return "out_of_scope", f"refused:{kind}"
    intent = _rule_intent(ql)
    if intent is not None:
        return intent, f"rule:{intent}"
    match = nlu.route(ql)
    if match.decision == "route":
        return match.intent, "search"
    if match.decision == "clarify":
        return "clarify", "ambiguous"
    return "out_of_scope", "unknown"


def route_intent(question: str) -> str:
    return route_detail(question)[0]


# The plan is a pure function of (merchant, question, window) over immutable marts, and a
# demo asks the same handful of questions repeatedly. Callers only read the result — the
# gateway copies `refs` into the response and serialises it. Invalidated by db.reset().
@lru_cache(maxsize=512)
def _plan(m: str, question: str, f: str, t: str) -> _Plan:
    intent, why = route_detail(question)
    if intent == "out_of_scope":
        # A question refused by a safety family and a question the router simply did not
        # recognise are different situations and deserve different answers. Telling a
        # merchant who asked something vague-but-legitimate that their question "cannot be
        # computed from your payment data" is both wrong and unhelpful.
        return _ans_out_of_scope() if why.startswith("refused:") else _ans_unrecognised(question)
    if intent == "clarify":
        return _ans_clarify(nlu.route(question.strip()))
    return _ANSWER[intent](m, f, t, question)


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
        suggestions=p.suggestions,
    )
    return resp.to_dict()
