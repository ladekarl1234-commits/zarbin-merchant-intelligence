"""Metric registry — the single source of truth for metric semantics.

Every number surfaced by the product references a metric here. The evidence
drawer renders exactly what this module returns: definition, formula, the SQL
that actually ran, its parameters, sample sizes and caveats. Nothing is
hand-written per UI card.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .config import CUSTOMER_SCOPE_CAVEAT, FEE_CAVEAT


@dataclass(frozen=True)
class Metric:
    id: str
    name_fa: str
    definition_fa: str
    formula_fa: str
    grain: str
    caveats: tuple[str, ...] = field(default_factory=tuple)


_M = [
    Metric("sessions", "جلسه‌های پرداخت", "تعداد جلسه‌های پرداخت ایجادشده (هر session_key یک بار).",
           "count(distinct session_key)", "session"),
    Metric("verified", "پرداخت‌های موفق", "جلسه‌هایی که به وضعیت Verified رسیده‌اند؛ تعریف رسمی موفقیت در این محصول.",
           "count(sessions where outcome = verified)", "session"),
    Metric("gmv", "فروش موفق (GMV)", "جمع مبلغ جلسه‌های Verified. هر جلسه فقط یک بار شمرده می‌شود؛ تلاش‌های تکراری مبلغ را چند برابر نمی‌کنند.",
           "sum(amount | outcome = verified)", "session",
           ("مبالغ به ریال است.",)),
    Metric("conv", "نرخ تبدیل نهایی", "سهم جلسه‌هایی که در نهایت Verified شدند از کل جلسه‌های ایجادشده.",
           "verified ÷ sessions", "session"),
    Metric("first_try_conv", "نرخ موفقیت در اولین تلاش", "سهم جلسه‌هایی که همان تلاش اول آن‌ها به پرداخت موفقِ تاییدشده (Verified) رسید.",
           "first_try_verified ÷ sessions", "session"),
    Metric("attempt_rate", "نرخ اقدام به پرداخت", "سهم جلسه‌هایی که دست‌کم یک تلاش واقعی پرداخت (try_seq>0) داشتند.",
           "attempted ÷ sessions", "session"),
    Metric("no_attempt_rate", "نرخ انصراف پیش از پرداخت", "سهم جلسه‌هایی که هیچ تلاش پرداختی ثبت نکردند (NoAttempt). این حالت با خطای بانکی تفاوت دارد: پرداخت‌کننده اصلاً به درگاه نرسیده است.",
           "no_attempt ÷ sessions", "session"),
    Metric("inbank_abandon_rate", "رهاشدن در بانک", "سهم جلسه‌هایی که آخرین تلاش آن‌ها به بانک رفت (InBank) اما نتیجه موفقی برنگشت.",
           "abandoned_inbank ÷ sessions", "session"),
    Metric("failed_bank_rate", "خطای صریح بانکی", "سهم جلسه‌هایی که آخرین تلاش آن‌ها با خطای صریح (Failed) پایان یافت.",
           "failed_bank ÷ sessions", "session"),
    Metric("median_ticket", "میانه مبلغ تراکنش", "میانه مبلغ جلسه‌های Verified.",
           "median(amount | outcome = verified)", "session"),
    Metric("recovered", "پرداخت‌های نجات‌یافته", "جلسه‌های موفقی که تلاش اول آن‌ها ناموفق بود و با تلاش مجدد در همان جلسه به نتیجه رسیدند.",
           "count(success sessions with n_tries>1 and first try not ok)", "session"),
    Metric("recovery_rate", "نرخ بازیابی پس از شکست اول", "از جلسه‌هایی که تلاش اولشان ناموفق بود، چه سهمی در نهایت به پرداخت موفقِ Verified رسیدند.",
           "recovered(Verified) ÷ (attempted − first_try_ok)", "session",
           ("«موفق» در این نرخ یعنی Verified؛ جلسه‌هایی که پس از تلاش مجدد فقط Paid شدند در صورت کسر نمی‌آیند و در «پرداخت‌های تاییدنشده» دیده می‌شوند.",)),
    Metric("paid_unverified", "پرداخت‌های تاییدنشده", "جلسه‌هایی که پول در بانک تسویه شده (settled_at ثبت شده) اما پذیرنده هرگز آن‌ها را Verify نکرده است.",
           "count(sessions where outcome = paid_unverified)", "session",
           ("این مبلغ برآورد نیست؛ پرداخت واقعاً انجام شده و فقط مرحله تایید پذیرنده انجام نشده است.",)),
    Metric("customers", "مشتریان پرداخت‌کننده", "تعداد کارت‌های یکتای پرداخت‌کننده موفق نزد همین پذیرنده.",
           "count(distinct payer_card_key | outcome = verified)", "customer",
           (CUSTOMER_SCOPE_CAVEAT,)),
    Metric("repeat_customer_share", "سهم مشتریان تکراری", "سهم مشتریانی که بیش از یک پرداخت موفق داشته‌اند.",
           "customers with n_verified>1 ÷ customers", "customer", (CUSTOMER_SCOPE_CAVEAT,)),
    Metric("repeat_txn_share", "سهم تراکنش از مشتریان تکراری", "سهم پرداخت‌های موفقی که توسط مشتریان تکراری انجام شده است.",
           "verified txns of repeat customers ÷ all verified txns", "customer", (CUSTOMER_SCOPE_CAVEAT,)),
    Metric("repeat_gmv_share", "سهم فروش از مشتریان تکراری", "سهم GMV که توسط مشتریان تکراری ایجاد شده است.",
           "gmv of repeat customers ÷ gmv", "customer", (CUSTOMER_SCOPE_CAVEAT,)),
    Metric("customer_concentration", "تمرکز مشتری", "سهم ۵ مشتری برتر از فروش موفق دوره.",
           "gmv(top 5 customers) ÷ gmv", "customer", (CUSTOMER_SCOPE_CAVEAT,)),
    Metric("fee_index", "شاخص نسبی کارمزد", "جمع adjusted_fee جلسه‌های موفق؛ فقط برای مقایسه نسبی معتبر است.",
           "sum(adjusted_fee | outcome = verified)", "session", (FEE_CAVEAT,)),
    Metric("peer_percentile", "جایگاه در میان همتایان", "رتبه صدکی این پذیرنده در میان گروه همتایان توضیح‌پذیر (هم‌صنف و هم‌مقیاس).",
           "exact rank among peers ÷ (n peers)", "merchant",
           ("اگر تعداد همتایان کافی نباشد این مقایسه نمایش داده نمی‌شود.",)),
    Metric("gmv_decomposition", "تجزیه تغییر فروش", "تجزیه دقیق تغییر GMV به سه عامل: تعداد جلسه‌ها، نرخ تبدیل و مبلغ متوسط، با روش میانگین لگاریتمی (LMDI) که مجموع سهم‌ها دقیقاً برابر کل تغییر است.",
           "ΔGMV = Σ L(G₂,G₁)·ln(fᵢ₂/fᵢ₁)", "merchant-period"),
    Metric("opportunity", "فرصت قابل بازیابی", "برآورد بازه‌ای ارزش قابل بازیابی: جلسه‌های در معرض × شکاف تا خط پایه همتایان × نرخ تبدیل و تیکت خود پذیرنده. جمع سادهٔ مبالغ ناموفق نیست.",
           "excess_rate × sessions × conv(own) × median_ticket(own)", "merchant-period",
           ("بازه از خط پایه میانه (کف) و چارک برتر (سقف) همتایان ساخته می‌شود؛ ادعای علیت ندارد.",)),
]

REGISTRY: dict[str, Metric] = {m.id: m for m in _M}


def evidence(metric_id: str, *, sql: str, params: dict, n: int | None = None,
             period: str | None = None, extra: dict | None = None,
             sql_kind: str = "query") -> dict:
    """Build the evidence payload the UI's drawer renders.

    sql_kind="query": `sql` is the literal query that ran (drawer: «کوئری اجراشده»).
    sql_kind="method": `sql` is representative method/pseudo-code because the figure is
    assembled from several aggregates (drawer: «روش محاسبه») — kept honest, never labeled
    as the exact executed query.
    """
    m = REGISTRY[metric_id]
    return {
        "metric_id": m.id,
        "name_fa": m.name_fa,
        "definition_fa": m.definition_fa,
        "formula": m.formula_fa,
        "grain": m.grain,
        "caveats": list(m.caveats),
        "sql": sql.strip(),
        "sql_kind": sql_kind,
        "params": params,
        "n": n,
        "period": period,
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **(extra or {}),
    }
