"""Insight / opportunity engine.

Every generator returns either None (insufficient evidence — restraint is a feature)
or a card: Observation → Diagnosis → Quantified impact (interval) → Action →
Confidence → Evidence. Opportunity values are counterfactual gaps against the
merchant's explainable peer baseline — never the naive sum of failed amounts.

Ranking: score = impact valued in IRR × confidence weight ÷ effort weight. Count-denominated
cards are converted to IRR for scoring only, so counts never compete against rials (ZB-015).

Every rial-denominated *estimate* is capped at the merchant's realized GMV in one shared place
(`_apply_gmv_cap`) so no generator can publish an opportunity larger than the whole business (ZB-006).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from .analytics import changes, period_agg
from .config import MIN_CUSTOMERS_RETENTION, MIN_SESSIONS_INSIGHT
from .db import q, q1
from .fa import fa_digits, fa_money, fa_num, fa_pct
from .peers import _quantile, peer_group, peer_period_rates
from .registry import evidence

CONF_W = {"high": 1.0, "medium": 0.6, "low": 0.35}
EFFORT_W = {"easy": 1.0, "medium": 1.5, "hard": 2.5}

# a paid-but-unverified session older than this is unlikely to be self-serve recoverable.
# NOTE: ZarinPal's actual verification/reversal window is NOT in the dataset — this only
# separates "fresh" from "aged" backlog and says so; it never asserts a policy (ZB-029).
FRESH_DAYS = 30

# A merchant this small cannot support a peer-benchmarked *estimate*, but an objectively broken
# funnel (2.8% conversion on 36 sessions) still deserves to be told — silence there is a false
# negative, not restraint (ZB-003). The absolute card quotes no opportunity figure and is
# explicitly low-confidence below MIN_SESSIONS_INSIGHT.
MIN_SIGNAL_SESSIONS = 10


def _fmt_period(f, t):
    return f"{f} تا {t}"


def _conf(n_sessions: int, n_peers: int) -> str:
    if n_sessions >= 2000 and n_peers >= 8:
        return "high"
    if n_sessions >= 500 and n_peers >= 5:
        return "medium"
    return "low"


# which session outcome's own amount distribution values each gap's recoverable sessions
_GAP_OUTCOME = {"no_attempt_rate": "no_attempt", "inbank_abandon_rate": "abandoned_inbank"}

_PEER_RATE_SQL = (
    "-- your rate vs same-period peer rates (from merchant_daily):\n"
    "SELECT merchant_key,\n"
    "       sum({num})/nullif(sum(sessions),0) AS rate\n"
    "FROM merchant_daily\n"
    "WHERE merchant_key IN (peer_keys) AND d BETWEEN $f AND $t\n"
    "GROUP BY merchant_key HAVING sum(sessions) >= 100;\n"
    "-- baseline = median(rate) across peers; opportunity per formula below."
)
_GAP_NUM = {"no_attempt_rate": "no_attempt", "inbank_abandon_rate": "abandoned_inbank"}


@dataclass
class _Ctx:
    """Everything the generators need, computed once (ZB-024: no per-card re-querying)."""
    m: str
    f: str
    t: str
    me: dict
    g: dict
    peers_rates: list
    tickets: dict            # outcome -> median amount, one query for all outcomes
    stats: dict = field(default_factory=dict)

    def ticket(self, outcome: str) -> float:
        """Median amount of an outcome's sessions, falling back to verified, then 0."""
        return self.tickets.get(outcome) or self.tickets.get("verified") or 0


def _period_tickets(m: str, f: str, t: str) -> dict:
    """Median amount per outcome in ONE query (was one query per card — ZB-024)."""
    rows = q("""SELECT outcome, quantile_cont(amount, 0.5) AS v
                FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t
                GROUP BY outcome""", {"m": m, "f": f, "t": t})
    return {r["outcome"]: r["v"] for r in rows}


@lru_cache(maxsize=1)
def _platform_floors() -> dict:
    """Platform-wide medians used as an absolute baseline when a merchant has no peer group.

    Without this, a merchant whose peer pool is too small gets an empty dashboard even when its
    own funnel is objectively broken (ZB-003).
    """
    r = q1("""SELECT quantile_cont(na, 0.5) AS na, quantile_cont(cv, 0.5) AS conv
              FROM (SELECT merchant_key,
                           sum(no_attempt)/nullif(sum(sessions),0) AS na,
                           sum(verified)/nullif(sum(sessions),0)   AS cv
                    FROM merchant_daily GROUP BY 1 HAVING sum(sessions) >= 100)""")
    return {"no_attempt_rate": r.get("na") or 0.07, "conv": r.get("conv") or 0.54}


def _gap_card(ctx: _Ctx, *, kind, rate_key, title_fa, diagnosis_fa, action_fa,
              effort, metric_id, extra_note=None):
    """A 'your loss-rate exceeds the peer median' opportunity.

    Opportunity is a counterfactual interval, NOT the sum of failed amounts:
      recoverable = (your_rate − peer_median) × sessions × recovery_fraction × ticket
    where ticket is the median amount of the SAME loss outcome's sessions (the sessions
    we claim to recover), and recovery_fraction spans [0.5 … 1.0] — an honest band for
    "how much of the gap actually closes", not a statistical confidence interval.
    """
    me, f, t = ctx.me, ctx.f, ctx.t
    mine = me.get(rate_key)
    vals = sorted(v[rate_key] for v in ctx.peers_rates if v.get(rate_key) is not None)
    if mine is None or len(vals) < 5:
        return None
    p50 = _quantile(vals, 0.5)
    gap_mid = mine - p50
    if gap_mid < 0.02:  # less than 2pp worse than peer median → not worth a card
        return None
    sessions = me["sessions"]
    n_peers = len(vals)
    outcome = _GAP_OUTCOME.get(rate_key, "verified")
    ticket = ctx.ticket(outcome)
    # scenario range, NOT a confidence interval: how much of the peer gap actually closes.
    excess_sessions = gap_mid * sessions
    lo = round(excess_sessions * 0.5 * ticket)   # conservative scenario: half the gap recovers
    mid = round(excess_sessions * 0.75 * ticket)  # most-likely point estimate
    hi = round(excess_sessions * 1.0 * ticket)   # optimistic scenario: gap fully closes
    if hi <= 0:
        return None

    broken = mine > 0.5  # more than half of sessions lost at this stage → infra problem
    conf = "low" if n_peers < 8 else _conf(sessions, n_peers)
    label = "برآورد فرصت (سناریوی محافظه‌کارانه تا خوش‌بینانه، نه بازه اطمینان آماری)"
    if broken:
        label = "این مرحله بیش از نیمی از پرداخت‌ها را از دست می‌دهد — ابتدا زیرساخت را رفع کنید"
        conf = "high"

    peer_note = ("توجه: گروه همتایان کوچک است (کمتر از ۸ پذیرنده)، پس این برآورد نامطمئن‌تر است. "
                 if n_peers < 8 else "")
    return {
        "id": f"{kind}", "kind": kind, "card_type": "opportunity",
        "title_fa": title_fa,
        "observation_fa": f"نرخ شما {fa_pct(mine)} است؛ میانه همتایان {fa_pct(p50)} (اختلاف {fa_digits(f'{gap_mid*100:.1f}')} واحد درصد، بر پایه {fa_num(n_peers)} همتا).",
        "diagnosis_fa": diagnosis_fa,
        "action_fa": action_fa,
        "impact_low": lo, "impact_mid": mid, "impact_high": hi,
        "impact_label_fa": label,
        "confidence": conf, "effort": effort,
        "n": int(sessions), "n_peers": n_peers, "broken": broken,
        "evidence": [evidence(metric_id, sql_kind="method",
                              sql=_PEER_RATE_SQL.replace("{num}", _GAP_NUM.get(rate_key, "verified")),
                              params={"m": ctx.m, "f": f, "t": t, "peers_n": n_peers,
                                      "peer_median_rate": round(p50, 4), "your_rate": round(mine, 4),
                                      "excess_sessions": round(excess_sessions),
                                      "ticket_outcome": outcome, "median_ticket_of_outcome": round(ticket)},
                              n=int(sessions), period=_fmt_period(f, t),
                              extra={"note_fa": (extra_note or "") + " " + peer_note}),
                     evidence("opportunity", sql_kind="method",
                              sql=("recoverable = (your_rate − peer_median) × sessions "
                                   "× recovery_fraction × median_ticket_of_lost_sessions;\n"
                                   f"= ({round(mine,4)} − {round(p50,4)}) × {int(sessions)} "
                                   f"× [0.5 … 0.75 … 1.0] × {round(ticket):,}"),
                              params={"recovery_fraction_low": 0.5, "recovery_fraction_mid": 0.75,
                                      "recovery_fraction_high": 1.0},
                              n=int(sessions), period=_fmt_period(f, t))],
    }


# --------------------------------------------------------------------------------------------
# card generators — one function each, individually testable (ZB-012)
# --------------------------------------------------------------------------------------------

def _card_paid_unverified(ctx: _Ctx):
    """Settled-but-unverified money. Diagnosis is driven by verify_type: for Automated
    merchants (≈100% of this dataset) telling them to 'enable auto-verify' is wrong — the
    verify callback is failing (ZB-028). Split by age instead of asserting a policy (ZB-029)."""
    me, m, f, t = ctx.me, ctx.m, ctx.f, ctx.t
    if not (me["paid_unverified"] >= 5 and me["paid_unverified_amount"] > 0):
        return None
    d = q1("""SELECT count(*) AS n, sum(amount) AS amt,
                     count(*) FILTER (WHERE age <= $fresh) AS n_fresh,
                     coalesce(sum(amount) FILTER (WHERE age <= $fresh), 0) AS amt_fresh,
                     mode(verify_type) AS verify_type, mode(win_psp) AS psp
              FROM (SELECT amount, verify_type, win_psp,
                           datediff('day', CAST(settled_at AS DATE), CAST($t AS DATE)) AS age
                    FROM sessions
                    WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='paid_unverified')""",
           {"m": m, "f": f, "t": t, "fresh": FRESH_DAYS})
    n, amt = int(d["n"] or 0), d["amt"] or 0
    if not n or amt <= 0:
        return None
    n_fresh, amt_fresh = int(d["n_fresh"] or 0), d["amt_fresh"] or 0
    automated = (d.get("verify_type") or "Automated") == "Automated"
    psp = d.get("psp")

    if automated:
        diagnosis = ("تایید این فروشگاه «خودکار» تنظیم شده است، پس مشکل فراموش‌کردن تایید دستی نیست: "
                     "فراخوانی تایید (verify/callback) از سمت فروشگاه شما به نتیجه نرسیده است"
                     + (f" — بیشترین این پرداخت‌ها روی درگاه {psp} بوده است." if psp else "."))
        action = ("لاگ خطای فراخوانی verify را در سرور فروشگاه بررسی کنید (تایم‌اوت، خطای شبکه یا پاسخ نامعتبر)، "
                  "و تا رفع مشکل، این پرداخت‌ها را از پیشخوان زرین‌پال دستی تعیین تکلیف کنید.")
    else:
        diagnosis = "تایید این فروشگاه دستی است و این پرداخت‌ها تایید نشده‌اند."
        action = "تایید خودکار تراکنش‌ها را فعال کنید تا این مرحله فراموش نشود."

    age_note = ""
    if n_fresh < n:
        # "پایانی این بازه" not "اخیر": the age is measured from the END OF THE SELECTED PERIOD,
        # so on a historical window "recent" would be misleading.
        age_note = (f" از این میان {fa_num(n_fresh)} پرداخت به مبلغ {fa_money(amt_fresh)} در "
                    f"{fa_num(FRESH_DAYS)} روز پایانیِ همین بازه تسویه شده و بقیه قدیمی‌ترند.")
    return {
        "id": "paid_unverified", "kind": "paid_unverified", "card_type": "opportunity",
        "title_fa": "پرداخت‌های تاییدنشده — پول رسیده اما تایید نشده",
        "observation_fa": (f"{fa_num(n)} پرداخت به مبلغ {fa_money(amt)} در این دوره در بانک تسویه شده، "
                           f"اما مرحله تایید نهایی سمت فروشگاه شما انجام نشده است.{age_note}"),
        "diagnosis_fa": diagnosis,
        "action_fa": action,
        "impact_low": round(amt), "impact_high": round(amt),
        "impact_label_fa": "مبلغ واقعی در انتظار تعیین تکلیف (برآورد نیست)",
        "impact_is_realized": True,   # a realized sum, never capped against GMV
        "confidence": "high", "effort": "easy", "n": n,
        "evidence": [evidence("paid_unverified",
                              sql=("SELECT count(*), sum(amount), mode(verify_type), mode(win_psp)\n"
                                   "FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t\n"
                                   "  AND outcome='paid_unverified'"),
                              params={"m": m, "f": f, "t": t, "verify_type": d.get("verify_type"),
                                      "top_psp": psp, "fresh_days": FRESH_DAYS,
                                      "n_fresh": n_fresh, "amount_fresh": round(amt_fresh)},
                              n=n, period=_fmt_period(f, t),
                              extra={"note_fa": ("پنجره مجاز تایید/برگشت در دیتاست موجود نیست؛ تفکیک «اخیر/قدیمی» "
                                                 "فقط بر پایه فاصله زمانی تسویه است و ادعای سیاست زرین‌پال ندارد.")})],
    }


def _card_no_attempt_gap(ctx: _Ctx):
    if ctx.me["sessions"] < MIN_SESSIONS_INSIGHT:
        return None
    return _gap_card(ctx, kind="no_attempt_gap", rate_key="no_attempt_rate",
                     title_fa="انصراف پیش از پرداخت بالاتر از همتایان",
                     diagnosis_fa="مشتری جلسه پرداخت را می‌سازد اما هرگز به درگاه نمی‌رسد؛ معمولاً مشکل در ریدایرکت، سبد خرید یا اپلیکیشن شماست، نه بانک.",
                     action_fa="مسیر انتقال به درگاه را روی موبایل و دسکتاپ تست کنید؛ خطاهای ریدایرکت و تایم‌اوت سمت خودتان را لاگ و رفع کنید.",
                     effort="medium", metric_id="no_attempt_rate")


def _card_inbank_gap(ctx: _Ctx):
    if ctx.me["sessions"] < MIN_SESSIONS_INSIGHT:
        return None
    return _gap_card(ctx, kind="inbank_gap", rate_key="inbank_abandon_rate",
                     title_fa="رهاشدن در صفحه بانک بیش از همتایان",
                     diagnosis_fa="پرداخت‌کننده به صفحه بانک می‌رسد اما تراکنش کامل نمی‌شود (انصراف، خطای کارت، یا اصطکاک صفحه پرداخت).",
                     action_fa="با پشتیبانی زرین‌پال درباره درگاه/PSP جایگزین صحبت کنید و مبلغ‌های پرتکرار شکست را بررسی کنید.",
                     effort="medium", metric_id="inbank_abandon_rate")


def _card_recovery_gap(ctx: _Ctx):
    me, m, f, t = ctx.me, ctx.m, ctx.f, ctx.t
    if me["sessions"] < MIN_SESSIONS_INSIGHT:
        return None
    fp = me["attempted"] - me["first_try_ok"]
    if fp < MIN_SESSIONS_INSIGHT:
        return None
    mine_rr = me["recovered"] / fp
    vals = sorted(v["recovery_rate"] for v in ctx.peers_rates if v.get("recovery_rate") is not None)
    if len(vals) < 5:
        return None
    p50 = _quantile(vals, 0.5)
    gap = p50 - mine_rr
    if gap <= 0.03:
        return None
    ticket = ctx.ticket("verified")
    lo, hi = gap * fp * ticket * 0.5, gap * fp * ticket
    if hi <= 0:
        return None
    return {
        "id": "recovery_gap", "kind": "recovery_gap", "card_type": "opportunity",
        "title_fa": "تلاش مجدد کمتر از همتایان به نتیجه می‌رسد",
        "observation_fa": f"از {fa_num(fp)} جلسه‌ای که تلاش اولشان ناموفق بود فقط {fa_pct(mine_rr)} نجات یافت؛ میانه همتایان {fa_pct(p50)}.",
        "diagnosis_fa": "پس از شکست اول، مشتری مسیر ساده‌ای برای تلاش دوباره ندارد یا صفحه پرداخت به او پیشنهاد تکرار نمی‌دهد.",
        "action_fa": "دکمه «پرداخت مجدد» را بلافاصله پس از شکست نمایش دهید و جلسه را تا انقضای ۳۰ دقیقه‌ای زنده نگه دارید.",
        "impact_low": round(lo), "impact_high": round(hi),
        "impact_label_fa": "برآورد فروش قابل نجات در این دوره",
        "confidence": _conf(fp, len(vals)), "effort": "easy", "n": int(fp),
        "evidence": [evidence("recovery_rate",
                              sql="SELECT sum(recovered::int)/nullif(sum((attempted AND NOT first_try_ok)::int),0) FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t",
                              params={"m": m, "f": f, "t": t, "own": round(mine_rr, 4),
                                      "peer_p50": round(p50, 4), "peers_n": len(vals)},
                              n=int(fp), period=_fmt_period(f, t))],
    }


def _card_high_value_friction(ctx: _Ctx):
    """Top amount quintile vs middle, within-merchant.

    ntile ORDER BY carries a unique tiebreaker: without it, tied amounts (constant in payments)
    land in different quintiles on each run and the card returns different money every time (ZB-120).
    """
    m, f, t = ctx.m, ctx.f, ctx.t
    if ctx.me["sessions"] < MIN_SESSIONS_INSIGHT:
        return None
    hv = q1("""
        WITH b AS (SELECT amount, outcome,
                          ntile(5) OVER (ORDER BY amount, session_key) AS band
                   FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t)
        SELECT count(*) FILTER (WHERE band=5) AS n_top,
               avg((outcome='verified')::int) FILTER (WHERE band=5) AS conv_top,
               avg((outcome='verified')::int) FILTER (WHERE band IN (2,3,4)) AS conv_mid,
               avg(amount) FILTER (WHERE band=5 AND outcome!='verified') AS avg_lost_amount
        FROM b""", {"m": m, "f": f, "t": t})
    if (hv.get("n_top") or 0) < MIN_SESSIONS_INSIGHT or hv["conv_top"] is None or not hv["conv_mid"]:
        return None
    gap = hv["conv_mid"] - hv["conv_top"]
    if gap <= 0.05:
        return None
    n_top = hv["n_top"]
    lo = gap * 0.5 * n_top * (hv["avg_lost_amount"] or 0)
    hi = gap * n_top * (hv["avg_lost_amount"] or 0)
    if hi <= 0:
        return None
    return {
        "id": "high_value_friction", "kind": "high_value_friction", "card_type": "opportunity",
        "title_fa": "پرداخت‌های گران‌قیمت بیشتر شکست می‌خورند",
        "observation_fa": f"نرخ تبدیل پنجک بالای مبلغ {fa_pct(hv['conv_top'])} است؛ {fa_digits(f'{gap*100:.1f}')} واحد درصد کمتر از مبالغ میانی خودتان.",
        "diagnosis_fa": "در مبالغ بالا سقف کارت، خطای بانک یا تردید مشتری پررنگ‌تر است؛ این مقایسه درون داده خود شماست و اثر ترکیب پذیرنده‌ها را ندارد.",
        "action_fa": "برای سفارش‌های گران پرداخت قسطی/دومرحله‌ای یا کارت‌به‌کارت جایگزین پیشنهاد دهید و سقف کارت را قبل از پرداخت یادآوری کنید.",
        "impact_low": round(lo), "impact_high": round(hi),
        "impact_label_fa": "برآورد فروش در معرض اصطکاک مبلغ بالا",
        "confidence": _conf(n_top, 8), "effort": "medium", "n": int(n_top),
        "evidence": [evidence("conv", sql_kind="method",
                              sql="ntile(5) OVER (ORDER BY amount, session_key) within merchant; conv(top) vs conv(mid)",
                              params={"m": m, "f": f, "t": t, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in hv.items()}},
                              n=int(n_top), period=_fmt_period(f, t),
                              extra={"note_fa": "مقایسه فقط درون جلسه‌های همین پذیرنده انجام می‌شود تا مخدوش‌کننده ترکیب پذیرنده/صنف حذف شود."})],
    }


def _card_repeat_gap(ctx: _Ctx):
    m, stats, g = ctx.m, ctx.stats, ctx.g
    if not (stats and (stats.get("customers") or 0) >= MIN_CUSTOMERS_RETENTION and g.get("sufficient")):
        return None
    peers_repeat = [r["repeat_txns"] / r["cust_txns"] for r in _peer_repeat(g["peers"]) if r["cust_txns"]]
    mine_share = stats["repeat_txns"] / stats["cust_txns"] if stats["cust_txns"] else None
    if mine_share is None or len(peers_repeat) < 5:
        return None
    vals = sorted(peers_repeat)
    p50 = _quantile(vals, 0.5)
    if p50 - mine_share <= 0.05:
        return None
    extra_txns = (p50 - mine_share) * stats["cust_txns"]
    ticket = stats["median_ticket"] or 0
    if extra_txns * ticket <= 0:
        return None
    return {
        "id": "repeat_gap", "kind": "repeat_gap", "card_type": "opportunity",
        "title_fa": "مشتریان کمتر از همتایان برمی‌گردند",
        "observation_fa": f"{fa_pct(mine_share)} از پرداخت‌های موفق شما از مشتریان تکراری است؛ میانه همتایان {fa_pct(p50)}.",
        "diagnosis_fa": "جذب مشتری دارید اما نگه‌داشت ضعیف‌تر از پذیرندگان مشابه است.",
        "action_fa": "برای مشتریان یک‌بارخرید کمپین بازگشت (پیامک/کد تخفیف خرید دوم) اجرا کنید؛ اثر آن در همین گزارش قابل پیگیری است.",
        "impact_low": round(extra_txns * ticket * 0.4), "impact_high": round(extra_txns * ticket),
        "impact_label_fa": "برآورد فروش بالقوه از رسیدن به میانه همتایان",
        "confidence": "low", "effort": "hard", "n": int(stats["customers"]),
        "evidence": [evidence("repeat_txn_share", sql_kind="method",
                              sql="repeat_txns / cust_txns FROM merchant_stats; baseline = same ratio across peer group",
                              params={"m": m, "own": round(mine_share, 4), "peer_p50": round(p50, 4),
                                      "peers_n": len(vals)},
                              n=int(stats["cust_txns"]), period="کل بازه داده",
                              extra={"note_fa": "رفتار بازگشت در کل شش‌ماهه سنجیده می‌شود تا دوره‌های کوتاه گمراه‌کننده نباشند."})],
    }


def _card_concentration(ctx: _Ctx):
    m, f, t = ctx.m, ctx.f, ctx.t
    conc = q1("""
        WITH pc AS (SELECT payer_card_key, sum(amount) AS g FROM sessions
                    WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='verified' GROUP BY 1),
        r AS (SELECT g, row_number() OVER (ORDER BY g DESC, payer_card_key) AS rk FROM pc)
        SELECT coalesce(sum(g) FILTER (WHERE rk<=5),0)/nullif(sum(g),0) AS top5, count(*) AS n,
               coalesce(sum(g) FILTER (WHERE rk<=5),0) AS top5_gmv FROM r""", {"m": m, "f": f, "t": t})
    if (conc.get("n") or 0) < MIN_CUSTOMERS_RETENTION or (conc.get("top5") or 0) <= 0.4:
        return None
    return {
        "id": "concentration", "kind": "concentration", "card_type": "alert",
        "title_fa": "وابستگی فروش به چند مشتری معدود",
        "observation_fa": f"۵ مشتری برتر {fa_pct(conc['top5'], 0)} از فروش موفق این دوره را ساخته‌اند ({fa_money(conc['top5_gmv'])}).",
        "diagnosis_fa": "از دست دادن یکی از این مشتریان ضربه بزرگی به درآمد می‌زند؛ این یک ریسک است، نه فرصت فوری.",
        "action_fa": "برای مشتریان کلیدی قرارداد/مشوق وفاداری تعریف کنید و هم‌زمان جذب مشتری جدید را تقویت کنید.",
        "impact_low": 0, "impact_high": 0,
        "impact_label_fa": f"فروش در معرض ریسک: {fa_money(conc['top5_gmv'])}",
        "confidence": "high", "effort": "hard", "n": int(conc["n"]),
        "risk_gmv": conc["top5_gmv"],
        "evidence": [evidence("customer_concentration", sql_kind="method",
                              sql="SELECT sum(g) FILTER (rk<=5)/sum(g) FROM (per-card GMV ranked) WHERE merchant/period",
                              params={"m": m, "f": f, "t": t}, n=int(conc["n"]), period=_fmt_period(f, t))],
    }


def _card_psp_friction(ctx: _Ctx):
    """PSP-routing insight from within-merchant success rates.

    Compares FIRST attempts only (try_seq=1): a weak-looking rail is often just the retry rail,
    which by construction carries already-failed traffic — comparing all attempts manufactures a
    phantom gap (ZB-016). The gap must also hold in at least two of three amount terciles, so a
    difference driven purely by amount mix is not reported as a routing lever.
    """
    m, f, t = ctx.m, ctx.f, ctx.t
    if ctx.me["sessions"] < MIN_SESSIONS_INSIGHT:
        return None
    rows = q("""
        SELECT psp_code, count(*) AS attempts, avg(ok::int) AS ok_rate, sum(ok::int) AS successes
        FROM attempts
        WHERE merchant_key=$m AND d BETWEEN $f AND $t AND psp_code IS NOT NULL AND try_seq = 1
        GROUP BY psp_code HAVING count(*) >= 200 ORDER BY ok_rate, psp_code""", {"m": m, "f": f, "t": t})
    # Exclude degenerate/disabled rails: a PSP at ~0% success is a broken/off gateway, not a
    # "weak" one you can reroute away from — including it would manufacture a phantom opportunity.
    rows = [r for r in rows if r["ok_rate"] is not None and r["ok_rate"] >= 0.05 and r["successes"] >= 30]
    if len(rows) < 2:
        return None
    worst, best = rows[0], rows[-1]
    gap = best["ok_rate"] - worst["ok_rate"]
    if gap < 0.10:  # gateways perform similarly → no routing lever
        return None

    # confounder control: does the gap survive within amount terciles?
    bands = q("""
        WITH fa AS (
            SELECT psp_code, ok, amount,
                   ntile(3) OVER (ORDER BY amount, session_key, try_seq) AS band
            FROM attempts
            WHERE merchant_key=$m AND d BETWEEN $f AND $t AND try_seq = 1
                  AND psp_code IN ($w, $b))
        SELECT band, psp_code, avg(ok::int) AS ok_rate, count(*) AS n
        FROM fa GROUP BY 1, 2""",
        {"m": m, "f": f, "t": t, "w": worst["psp_code"], "b": best["psp_code"]})
    by_band: dict[int, dict[str, float]] = {}
    for r in bands:
        if (r["n"] or 0) >= 30:
            by_band.setdefault(int(r["band"]), {})[r["psp_code"]] = r["ok_rate"]
    holds = sum(1 for v in by_band.values()
                if worst["psp_code"] in v and best["psp_code"] in v
                and v[best["psp_code"]] > v[worst["psp_code"]])
    if holds < 2:
        return None

    codes = q("""
        SELECT switch_response_code AS code, count(*) AS n FROM attempts
        WHERE merchant_key=$m AND d BETWEEN $f AND $t AND psp_code=$p AND NOT ok
              AND switch_response_code IS NOT NULL
        GROUP BY 1 ORDER BY n DESC, code LIMIT 3""", {"m": m, "f": f, "t": t, "p": worst["psp_code"]})
    code_txt = ("؛ پرتکرارترین کدهای خطا: " + "، ".join(c["code"] for c in codes)) if codes else ""
    lost = round(worst["attempts"] * gap * 0.5)  # attempts a better PSP might have converted
    if lost <= 0:
        return None
    return {
        "id": "psp_friction", "kind": "psp_friction", "card_type": "opportunity",
        "title_fa": f"درگاه {worst['psp_code']} به‌طور محسوس ضعیف‌تر از بقیه عمل می‌کند",
        "observation_fa": (f"در تلاش‌های اول، نرخ موفقیت روی {worst['psp_code']} برابر {fa_pct(worst['ok_rate'])} است "
                           f"(روی {fa_num(worst['attempts'])} تلاش اول)، در حالی که {best['psp_code']} برای همین "
                           f"فروشگاه {fa_pct(best['ok_rate'])} موفقیت دارد — اختلاف {fa_digits(f'{gap*100:.0f}')} واحد درصد{code_txt}."),
        "diagnosis_fa": (f"مقایسه فقط روی تلاش‌های اولِ ترافیک خود شماست (تا اثر ترافیکِ ازپیش‌شکست‌خورده حذف شود) و "
                         f"این اختلاف در {fa_num(holds)} از ۳ بازه مبلغ هم برقرار می‌ماند؛ انتخاب درگاه سمت زرین‌پال انجام می‌شود."),
        "action_fa": f"از پشتیبانی زرین‌پال بخواهید سهم ترافیک را از {worst['psp_code']} به درگاه قوی‌تر منتقل کند و کدهای خطای پرتکرار را بررسی کنید.",
        "impact_low": round(lost * 0.5), "impact_high": lost,
        "impact_label_fa": "برآورد تلاش‌های قابل نجات با مسیردهی به درگاه بهتر (تعداد تراکنش)",
        "impact_is_count": True,
        "confidence": "medium" if worst["attempts"] >= 1000 else "low", "effort": "easy",
        "n": int(worst["attempts"]),
        "evidence": [evidence("first_try_conv",
                              sql=("SELECT psp_code, count(*) attempts, avg(ok::int) ok_rate\n"
                                   "FROM attempts WHERE merchant_key=$m AND d BETWEEN $f AND $t\n"
                                   "  AND psp_code IS NOT NULL AND try_seq = 1\n"
                                   "GROUP BY psp_code HAVING count(*) >= 200 ORDER BY ok_rate;"),
                              params={"m": m, "f": f, "t": t,
                                      "worst_psp": worst["psp_code"], "worst_rate": round(worst["ok_rate"], 4),
                                      "best_psp": best["psp_code"], "best_rate": round(best["ok_rate"], 4),
                                      "amount_terciles_holding": holds},
                              n=int(worst["attempts"]), period=_fmt_period(f, t),
                              extra={"note_fa": ("فقط تلاش‌های اول مقایسه می‌شوند؛ برآورد نجات = تلاش‌های درگاه ضعیف × "
                                                 "شکاف نرخ × ۰٫۵ (سهم محافظه‌کارانه‌ای که با درگاه بهتر موفق می‌شد).")})],
    }


def _card_absolute_funnel(ctx: _Ctx):
    """Fallback when the merchant has real volume but NO peer group.

    Without this a third of merchants see an empty dashboard and are told the silence is good
    news, even when their funnel is objectively broken (ZB-003). Uses a platform-wide floor
    instead of a matched peer baseline, and says so.
    """
    me, m, f, t = ctx.me, ctx.m, ctx.f, ctx.t
    if me["sessions"] < MIN_SIGNAL_SESSIONS:
        return None
    floors = _platform_floors()
    na, conv = me.get("no_attempt_rate"), me.get("conv")
    worst_na = na is not None and na > max(0.15, floors["no_attempt_rate"] * 2)
    worst_conv = conv is not None and conv < floors["conv"] * 0.6
    if not (worst_na or worst_conv):
        return None
    thin = me["sessions"] < MIN_SESSIONS_INSIGHT
    if worst_na:
        title = "انصراف پیش از پرداخت به‌طور غیرعادی بالاست"
        obs = (f"{fa_pct(na)} از جلسه‌های پرداخت شما هرگز به درگاه نرسیده‌اند؛ میانه کل پلتفرم "
               f"{fa_pct(floors['no_attempt_rate'])} است.")
        diag = "مشتری صفحه پرداخت را می‌سازد اما به بانک نمی‌رسد — این تقریباً همیشه مشکل مسیر/ریدایرکت سمت فروشگاه است، نه بانک."
        act = "مسیر انتقال به درگاه را روی موبایل و دسکتاپ تست کنید و خطاهای ریدایرکت/تایم‌اوت را لاگ کنید."
        metric = "no_attempt_rate"
    else:
        title = "نرخ تکمیل پرداخت به‌طور غیرعادی پایین است"
        obs = f"نرخ تکمیل پرداخت شما {fa_pct(conv)} است؛ میانه کل پلتفرم {fa_pct(floors['conv'])}."
        diag = "بخش بزرگی از مشتریانی که به صفحه پرداخت می‌رسند خرید را تمام نمی‌کنند."
        act = "صفحه «مسیر پرداخت» را باز کنید و ببینید ریزش در کدام مرحله (پیش از درگاه، در بانک، یا خطای بانکی) اتفاق می‌افتد."
        metric = "conv"
    return {
        "id": "absolute_funnel", "kind": "absolute_funnel", "card_type": "alert",
        "title_fa": title, "observation_fa": obs, "diagnosis_fa": diag, "action_fa": act,
        "impact_low": 0, "impact_high": 0,
        "impact_label_fa": "مقایسه با خط پایه کل پلتفرم (گروه همتای هم‌اندازه برای شما موجود نیست)",
        "confidence": "low" if thin else "medium", "effort": "medium", "n": int(me["sessions"]),
        "risk_gmv": 0, "low_n": thin,
        "evidence": [evidence(metric, sql_kind="method",
                              sql=("-- platform floor (median across merchants with >=100 sessions):\n"
                                   "SELECT quantile_cont(rate,0.5) FROM (per-merchant rate FROM merchant_daily)"),
                              params={"m": m, "f": f, "t": t,
                                      "your_rate": round(na if worst_na else conv, 4),
                                      "platform_median": round(floors["no_attempt_rate"] if worst_na else floors["conv"], 4)},
                              n=int(me["sessions"]), period=_fmt_period(f, t),
                              extra={"note_fa": ("چون گروه همتای هم‌صنف و هم‌اندازه کافی برای شما پیدا نشد، "
                                                 "مقایسه با میانه کل پلتفرم انجام شده که دقت کمتری دارد."
                                                 + (f" حجم داده شما کم است ({fa_num(me['sessions'])} جلسه)، "
                                                    "پس این فقط یک هشدار کیفی است و برآورد مالی همراه ندارد."
                                                    if thin else ""))})],
    }


def _card_change_alert(ctx: _Ctx):
    """GMV change between two EQUAL halves of the period.

    An odd-length window used to be split into unequal halves, so the sessions factor was
    biased by one extra day (ZB-018). The middle day is dropped instead.
    """
    m, f, t = ctx.m, ctx.f, ctx.t
    d1, d2 = date.fromisoformat(f), date.fromisoformat(t)
    n_days = (d2 - d1).days + 1
    if n_days < 28:
        return None
    half = n_days // 2                      # equal halves; middle day dropped when n_days is odd
    a_end = d1 + timedelta(days=half - 1)
    b_start = d2 - timedelta(days=half - 1)
    ch = changes(m, f, str(a_end), str(b_start), t)
    if not ch["decomposable"] or not ch["before"]["gmv"]:
        return None
    rel = ch["delta_gmv"] / ch["before"]["gmv"]
    if abs(rel) < 0.10:
        return None
    contrib = ch["contrib"]
    driver_key = max(contrib, key=lambda k: abs(contrib[k]))
    names = {"sessions": "تعداد جلسه‌های پرداخت", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط تراکنش"}
    direction = "رشد" if rel > 0 else "افت"
    worse = rel < 0
    action_by_driver = {
        "sessions": ("کاهش ترافیک عامل اصلی بوده — کانال‌های جذب و کمپین‌های نیمه دوم دوره را بررسی کنید و دلیل افت بازدید را پیدا کنید."
                     if worse else "رشد از ترافیک بیشتر آمده — همان کانال جذب موفق را تقویت و بودجه‌اش را حفظ کنید."),
        "conv": ("افت از نرخ تبدیل بوده — صفحه «مسیر پرداخت» را ببینید که کدام مرحله (بدون اقدام/بانک) بدتر شده و همان را رفع کنید."
                 if worse else "بهبود از نرخ تبدیل آمده — تغییری که این نرخ را بالا برده شناسایی و تثبیت کنید."),
        "ticket": ("افت از کوچک‌تر شدن سبد خرید بوده — پیشنهاد فروش مکمل/بسته‌ای برای بالا بردن مبلغ سفارش را امتحان کنید."
                   if worse else "رشد از بزرگ‌تر شدن سبد خرید آمده — همین ترکیب محصول/قیمت را حفظ کنید."),
    }
    return {
        "id": "gmv_change", "kind": "gmv_change", "card_type": "alert",
        "title_fa": f"{direction} {fa_pct(abs(rel), 0)} فروش در نیمه دوم دوره",
        "observation_fa": (f"فروش موفق از {fa_money(ch['before']['gmv'])} به {fa_money(ch['after']['gmv'])} رسید "
                           f"(دو نیمهٔ {fa_num(half)} روزه)."),
        "diagnosis_fa": f"بیشترین دلیل این تغییر «{names[driver_key]}» بوده است ({fa_money(contrib[driver_key])} از کل تغییر {fa_money(ch['delta_gmv'])}).",
        "action_fa": action_by_driver[driver_key],
        "impact_low": 0, "impact_high": 0,
        "impact_label_fa": f"تغییر کل فروش: {fa_money(ch['delta_gmv'])}",
        "confidence": "high", "effort": "easy", "n": int(ch["before"]["sessions"] + ch["after"]["sessions"]),
        "risk_gmv": abs(ch["delta_gmv"]),
        "days_per_half": half,
        "evidence": [ch["evidence"]],
    }


_GENERATORS = (
    _card_paid_unverified,
    _card_no_attempt_gap,
    _card_inbank_gap,
    _card_recovery_gap,
    _card_high_value_friction,
    _card_repeat_gap,
    _card_concentration,
    _card_psp_friction,
    _card_change_alert,
)


def _apply_gmv_cap(cards: list[dict], realized_gmv: float) -> None:
    """Clamp every rial-denominated ESTIMATE to the merchant's realized GMV, in one place.

    An "opportunity" larger than everything the merchant sold is a broken-funnel signal, not a
    recoverable number. Previously only the peer-gap generator capped, so other generators could
    publish an impact above 100% of realized GMV (ZB-006). Realized sums (paid-unverified) and
    count-denominated cards are exempt by construction.

    A merchant with ZERO realized sales is the extreme of the same case: any "recoverable" rial
    figure there is unsupportable (there is no demonstrated ability to convert at all). Such cards
    are converted to a funnel alert rather than published as money — an early-return here used to
    let them through UNCAPPED, which was worse than the bug this function exists to fix.
    """
    realized = realized_gmv or 0
    for c in cards:
        c.setdefault("capped", False)
        if c.get("impact_is_count") or c.get("impact_is_realized") or c["card_type"] != "opportunity":
            continue
        if realized <= 0:
            if (c.get("impact_high") or 0) > 0:
                c["impact_low"] = c["impact_high"] = 0
                c["impact_mid"] = None
                c["card_type"] = "alert"
                c["capped"] = True
                c["risk_gmv"] = 0
                c["impact_label_fa"] = ("در این دوره هیچ پرداخت موفقی ثبت نشده، پس برآورد ریالی "
                                        "قابل اتکا نیست — این یک هشدار خرابی مسیر پرداخت است.")
            continue
        if (c.get("impact_high") or 0) > realized:
            hi = round(realized)
            c["impact_high"] = hi
            c["impact_low"] = min(c.get("impact_low") or 0, hi)
            if c.get("impact_mid") is not None:
                c["impact_mid"] = min(c["impact_mid"], hi)
            c["capped"] = True
            if not c.get("broken"):
                c["impact_label_fa"] = "سقف واقع‌بینانه (محدود به کل فروش موفق دوره)"


def _score(cards: list[dict], ticket: float) -> None:
    """Rank on ONE unit. Count-denominated impacts are converted to IRR for scoring only, so a
    "178 transactions" card no longer loses to a rial card purely because of its unit (ZB-015)."""
    for c in cards:
        c.setdefault("card_type", "opportunity")
        if c["card_type"] != "opportunity":
            c["score"] = 0        # alerts are ordered after opportunities, by their own magnitude
            c["score_basis_irr"] = 0
            continue
        base = c.get("impact_high") or 0
        if c.get("impact_is_count"):
            base = base * (ticket or 0)
        c["score_basis_irr"] = round(base)
        c["score"] = round(base * CONF_W[c["confidence"]] / EFFORT_W[c["effort"]])


def generate(m: str, f: str, t: str) -> list[dict]:
    me = period_agg(m, f, t)
    me["m"] = m
    if not me["sessions"]:
        return []

    g = peer_group(m)
    ctx = _Ctx(
        m=m, f=f, t=t, me=me, g=g,
        peers_rates=peer_period_rates(g["peers"], f, t) if g.get("sufficient") else [],
        tickets=_period_tickets(m, f, t),
        stats=q1("SELECT * FROM merchant_stats WHERE merchant_key=$m", {"m": m}) or {},
    )

    cards = [c for c in (gen(ctx) for gen in _GENERATORS) if c]
    if not cards:
        # Last resort: rather than an empty dashboard that reads as "all clear", tell a merchant
        # whose funnel is objectively broken what we can see without a peer baseline (ZB-003).
        fallback = _card_absolute_funnel(ctx)
        if fallback:
            cards.append(fallback)
    _apply_gmv_cap(cards, me["gmv"] or 0)
    _score(cards, ctx.ticket("verified"))

    # Opportunities (recoverable rial) ALWAYS rank above alerts (risks/context with no
    # recoverable figure) — a zero-impact "sales grew" alert must never outrank real money.
    cards.sort(key=lambda c: (
        0 if c["card_type"] == "opportunity" else 1,
        -c["score"] if c["card_type"] == "opportunity" else -c.get("risk_gmv", 0),
        c["id"],
    ))
    return cards


def format_impact(card: dict) -> str:
    """Single source of truth for rendering a card's impact as Persian text.

    The copilot used to re-implement this and printed transaction counts as rial (ZB-013);
    every consumer must call this instead.
    """
    hi, lo = card.get("impact_high") or 0, card.get("impact_low") or 0
    if not hi:
        return card.get("impact_label_fa", "")
    if card.get("impact_is_count"):
        return f"{fa_num(lo)} تا {fa_num(hi)} تراکنش" if lo and lo != hi else f"{fa_num(hi)} تراکنش"
    mid = card.get("impact_mid")
    if mid:
        return f"{fa_money(mid)} (بین {fa_money(lo)} تا {fa_money(hi)})"
    return f"{fa_money(lo)} تا {fa_money(hi)}" if lo and lo != hi else fa_money(hi)


def _peer_repeat(keys: list[str]) -> list[dict]:
    return q("SELECT repeat_txns, cust_txns FROM merchant_stats WHERE merchant_key IN (SELECT unnest($k::varchar[]))",
             {"k": keys})
