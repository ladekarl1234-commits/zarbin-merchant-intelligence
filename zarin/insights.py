"""Insight / opportunity engine.

Every generator returns either None (insufficient evidence — restraint is a feature)
or a card: Observation → Diagnosis → Quantified impact (interval) → Action →
Confidence → Evidence. Opportunity values are counterfactual gaps against the
merchant's explainable peer baseline — never the naive sum of failed amounts.

Ranking: score = mid-impact (IRR) × confidence weight ÷ effort weight.
"""
from __future__ import annotations

from .analytics import changes, period_agg
from .config import MIN_CUSTOMERS_RETENTION, MIN_SESSIONS_INSIGHT
from .db import q1
from .fa import fa_digits, fa_money, fa_num, fa_pct
from .peers import _quantile, peer_group, peer_period_rates
from .registry import evidence

CONF_W = {"high": 1.0, "medium": 0.6, "low": 0.35}
EFFORT_W = {"easy": 1.0, "medium": 1.5, "hard": 2.5}


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


def _gap_card(*, kind, me, peers_rates, rate_key, f, t, title_fa, diagnosis_fa, action_fa,
              effort, metric_id, extra_note=None):
    """A 'your loss-rate exceeds the peer median' opportunity.

    Opportunity is a counterfactual interval, NOT the sum of failed amounts:
      recoverable = (your_rate − peer_median) × sessions × recovery_fraction × ticket
    where ticket is the median amount of the SAME loss outcome's sessions (the sessions
    we claim to recover), and recovery_fraction spans [0.5 … 1.0] — an honest band for
    "how much of the gap actually closes", not the spuriously-narrow p25↔p50 band.
    """
    mine = me.get(rate_key)
    vals = sorted(v[rate_key] for v in peers_rates if v.get(rate_key) is not None)
    if mine is None or len(vals) < 5:
        return None
    p50 = _quantile(vals, 0.5)
    gap_mid = mine - p50
    if gap_mid < 0.02:  # less than 2pp worse than peer median → not worth a card
        return None
    sessions = me["sessions"]
    n_peers = len(vals)
    # value the recoverable sessions at the median amount of the SAME loss outcome
    outcome = _GAP_OUTCOME.get(rate_key, "verified")
    ticket = q1("SELECT quantile_cont(amount,0.5) AS v FROM sessions "
                "WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome=$o",
                {"m": me["m"], "f": f, "t": t, "o": outcome})["v"] or \
        q1("SELECT quantile_cont(amount,0.5) AS v FROM sessions "
           "WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='verified'",
           {"m": me["m"], "f": f, "t": t})["v"] or 0
    excess_sessions = gap_mid * sessions
    lo = round(excess_sessions * 0.5 * ticket)   # conservative: half the gap recovers
    hi = round(excess_sessions * 1.0 * ticket)   # optimistic: gap closes to peer median
    if hi <= 0:
        return None

    # cap against realized GMV: an "opportunity" bigger than the merchant's whole realized
    # sales is a broken-funnel signal, not a recoverable number — cap and reframe.
    realized = me["gmv"] or 0
    capped = realized > 0 and hi > realized
    broken = mine > 0.5  # more than half of sessions lost at this stage → infra problem
    if capped:
        hi = round(realized)
        lo = min(lo, hi)

    # confidence: few peers can never be "high"; a broken funnel is high-confidence-problem
    conf = "low" if n_peers < 8 else _conf(sessions, n_peers)
    label = "برآورد فرصت قابل بازیابی در این دوره"
    if broken:
        label = "این مرحله بیش از نیمی از پرداخت‌ها را از دست می‌دهد — ابتدا زیرساخت را رفع کنید"
        conf = "high"
    elif capped:
        label = "سقف واقع‌بینانه (محدود به کل فروش موفق دوره)"

    peer_note = ("توجه: گروه همتایان کوچک است (کمتر از ۸ پذیرنده)، پس این برآورد نامطمئن‌تر است. "
                 if n_peers < 8 else "")
    return {
        "id": f"{kind}", "kind": kind, "card_type": "opportunity",
        "title_fa": title_fa,
        "observation_fa": f"نرخ شما {fa_pct(mine)} است؛ میانه همتایان {fa_pct(p50)} (اختلاف {fa_digits(f'{gap_mid*100:.1f}')} واحد درصد، بر پایه {fa_num(n_peers)} همتا).",
        "diagnosis_fa": diagnosis_fa,
        "action_fa": action_fa,
        "impact_low": lo, "impact_high": hi,
        "impact_label_fa": label,
        "confidence": conf, "effort": effort,
        "n": int(sessions), "n_peers": n_peers, "capped": capped, "broken": broken,
        "evidence": [evidence(metric_id,
                              sql=_PEER_RATE_SQL.replace("{num}", _GAP_NUM.get(rate_key, "verified")),
                              params={"m": me["m"], "f": f, "t": t, "peers_n": n_peers,
                                      "peer_median_rate": round(p50, 4), "your_rate": round(mine, 4),
                                      "excess_sessions": round(excess_sessions),
                                      "ticket_outcome": outcome, "median_ticket_of_outcome": round(ticket)},
                              n=int(sessions), period=_fmt_period(f, t),
                              extra={"note_fa": (extra_note or "") + " " + peer_note}),
                     evidence("opportunity",
                              sql=("recoverable = (your_rate − peer_median) × sessions "
                                   "× recovery_fraction × median_ticket_of_lost_sessions;\n"
                                   f"= ({round(mine,4)} − {round(p50,4)}) × {int(sessions)} "
                                   f"× [0.5 … 1.0] × {round(ticket):,}"),
                              params={"recovery_fraction_low": 0.5, "recovery_fraction_high": 1.0,
                                      "capped_at_realized_gmv": capped},
                              n=int(sessions), period=_fmt_period(f, t))],
    }


def generate(m: str, f: str, t: str) -> list[dict]:
    me = period_agg(m, f, t)
    me["m"] = m
    cards: list[dict] = []
    if not me["sessions"]:
        return []

    g = peer_group(m)
    peers_rates = peer_period_rates(g["peers"], f, t) if g.get("sufficient") else []

    # 1) paid-but-not-verified backlog — real settled money, direct action
    if me["paid_unverified"] >= 5 and me["paid_unverified_amount"] > 0:
        n, amt = int(me["paid_unverified"]), me["paid_unverified_amount"]
        cards.append({
            "id": "paid_unverified", "kind": "paid_unverified", "card_type": "opportunity",
            "title_fa": "پرداخت‌های تاییدنشده — پول رسیده اما تایید نشده",
            "observation_fa": f"{fa_num(n)} پرداخت به مبلغ {fa_money(amt)} در این دوره تسویه بانکی شده اما هرگز Verify نشده است.",
            "diagnosis_fa": "فراخوانی تایید (verify) سمت شما انجام نمی‌شود؛ معمولاً خطای کال‌بک یا وریفای دستی فراموش‌شده.",
            "action_fa": "تایید خودکار تراکنش‌ها را فعال یا خطای کال‌بک را برطرف کنید و این پرداخت‌ها را از پیشخوان زرین‌پال تعیین تکلیف کنید.",
            "impact_low": round(amt), "impact_high": round(amt),
            "impact_label_fa": "مبلغ واقعی در انتظار تعیین تکلیف (برآورد نیست)",
            "confidence": "high", "effort": "easy", "n": n,
            "evidence": [evidence("paid_unverified",
                                  sql="SELECT count(*), sum(amount) FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='paid_unverified'",
                                  params={"m": m, "f": f, "t": t}, n=n, period=_fmt_period(f, t))],
        })

    if me["sessions"] >= MIN_SESSIONS_INSIGHT:
        # 2) NoAttempt gap
        c = _gap_card(kind="no_attempt_gap", me=me, peers_rates=peers_rates, rate_key="no_attempt_rate",
                      f=f, t=t, title_fa="انصراف پیش از پرداخت بالاتر از همتایان",
                      diagnosis_fa="مشتری جلسه پرداخت را می‌سازد اما هرگز به درگاه نمی‌رسد؛ معمولاً مشکل در ریدایرکت، سبد خرید یا اپلیکیشن شماست، نه بانک.",
                      action_fa="مسیر انتقال به درگاه را روی موبایل و دسکتاپ تست کنید؛ خطاهای ریدایرکت و تایم‌اوت سمت خودتان را لاگ و رفع کنید.",
                      effort="medium", metric_id="no_attempt_rate")
        if c:
            cards.append(c)
        # 3) In-bank abandonment gap
        c = _gap_card(kind="inbank_gap", me=me, peers_rates=peers_rates, rate_key="inbank_abandon_rate",
                      f=f, t=t, title_fa="رهاشدن در صفحه بانک بیش از همتایان",
                      diagnosis_fa="پرداخت‌کننده به صفحه بانک می‌رسد اما تراکنش کامل نمی‌شود (انصراف، خطای کارت، یا اصطکاک صفحه پرداخت).",
                      action_fa="با پشتیبانی زرین‌پال درباره درگاه/PSP جایگزین صحبت کنید و مبلغ‌های پرتکرار شکست را بررسی کنید.",
                      effort="medium", metric_id="inbank_abandon_rate")
        if c:
            cards.append(c)
        # 4) recovery gap — merchant recovers fewer first-failures than peers
        fp = me["attempted"] - me["first_try_ok"]
        if fp >= MIN_SESSIONS_INSIGHT:
            mine_rr = me["recovered"] / fp
            vals = sorted(v["recovery_rate"] for v in peers_rates if v.get("recovery_rate") is not None)
            if len(vals) >= 5:
                p50 = _quantile(vals, 0.5)
                gap = p50 - mine_rr
                if gap > 0.03:
                    ticket = q1("SELECT quantile_cont(amount,0.5) AS v FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='verified'",
                                {"m": m, "f": f, "t": t})["v"] or 0
                    lo, hi = gap * fp * ticket * 0.5, gap * fp * ticket
                    cards.append({
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
                    })

        # 5) high-value friction — top amount quintile vs middle, within-merchant
        hv = q1("""
            WITH b AS (SELECT amount, outcome, ntile(5) OVER (ORDER BY amount) AS band
                       FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t)
            SELECT count(*) FILTER (WHERE band=5) AS n_top,
                   avg((outcome='verified')::int) FILTER (WHERE band=5) AS conv_top,
                   avg((outcome='verified')::int) FILTER (WHERE band IN (2,3,4)) AS conv_mid,
                   avg(amount) FILTER (WHERE band=5 AND outcome!='verified') AS avg_lost_amount
            FROM b""", {"m": m, "f": f, "t": t})
        if (hv.get("n_top") or 0) >= MIN_SESSIONS_INSIGHT and hv["conv_top"] is not None and hv["conv_mid"]:
            gap = hv["conv_mid"] - hv["conv_top"]
            if gap > 0.05:
                n_top = hv["n_top"]
                lo = gap * 0.5 * n_top * (hv["avg_lost_amount"] or 0)
                hi = gap * n_top * (hv["avg_lost_amount"] or 0)
                cards.append({
                    "id": "high_value_friction", "kind": "high_value_friction", "card_type": "opportunity",
                    "title_fa": "پرداخت‌های گران‌قیمت بیشتر شکست می‌خورند",
                    "observation_fa": f"نرخ تبدیل پنجک بالای مبلغ {fa_pct(hv['conv_top'])} است؛ {fa_digits(f'{gap*100:.1f}')} واحد درصد کمتر از مبالغ میانی خودتان.",
                    "diagnosis_fa": "در مبالغ بالا سقف کارت، خطای بانک یا تردید مشتری پررنگ‌تر است؛ این مقایسه درون داده خود شماست و اثر ترکیب پذیرنده‌ها را ندارد.",
                    "action_fa": "برای سفارش‌های گران پرداخت قسطی/دومرحله‌ای یا کارت‌به‌کارت جایگزین پیشنهاد دهید و سقف کارت را قبل از پرداخت یادآوری کنید.",
                    "impact_low": round(lo), "impact_high": round(hi),
                    "impact_label_fa": "برآورد فروش در معرض اصطکاک مبلغ بالا",
                    "confidence": _conf(n_top, 8), "effort": "medium", "n": int(n_top),
                    "evidence": [evidence("conv",
                                          sql="ntile(5) OVER (ORDER BY amount) within merchant; conv(top) vs conv(mid)",
                                          params={"m": m, "f": f, "t": t, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in hv.items()}},
                                          n=int(n_top), period=_fmt_period(f, t),
                                          extra={"note_fa": "مقایسه فقط درون جلسه‌های همین پذیرنده انجام می‌شود تا مخدوش‌کننده ترکیب پذیرنده/صنف حذف شود."})],
                })

    # 6) repeat gap vs peers (lifetime repeat behavior)
    stats = q1("SELECT * FROM merchant_stats WHERE merchant_key=$m", {"m": m})
    if stats and (stats["customers"] or 0) >= MIN_CUSTOMERS_RETENTION and g.get("sufficient"):
        peers_repeat = [r["repeat_txns"] / r["cust_txns"]
                        for r in __peer_repeat(g["peers"]) if r["cust_txns"]]
        mine_share = stats["repeat_txns"] / stats["cust_txns"] if stats["cust_txns"] else None
        if mine_share is not None and len(peers_repeat) >= 5:
            vals = sorted(peers_repeat)
            p50 = _quantile(vals, 0.5)
            if p50 - mine_share > 0.05:
                extra_txns = (p50 - mine_share) * stats["cust_txns"]
                ticket = stats["median_ticket"] or 0
                cards.append({
                    "id": "repeat_gap", "kind": "repeat_gap", "card_type": "opportunity",
                    "title_fa": "مشتریان کمتر از همتایان برمی‌گردند",
                    "observation_fa": f"{fa_pct(mine_share)} از پرداخت‌های موفق شما از مشتریان تکراری است؛ میانه همتایان {fa_pct(p50)}.",
                    "diagnosis_fa": "جذب مشتری دارید اما نگه‌داشت ضعیف‌تر از پذیرندگان مشابه است.",
                    "action_fa": "برای مشتریان یک‌بارخرید کمپین بازگشت (پیامک/کد تخفیف خرید دوم) اجرا کنید؛ اثر آن در همین گزارش قابل پیگیری است.",
                    "impact_low": round(extra_txns * ticket * 0.4), "impact_high": round(extra_txns * ticket),
                    "impact_label_fa": "برآورد فروش بالقوه از رسیدن به میانه همتایان",
                    "confidence": "low", "effort": "hard", "n": int(stats["customers"]),
                    "evidence": [evidence("repeat_txn_share",
                                          sql="repeat_txns / cust_txns FROM merchant_stats; baseline = same ratio across peer group",
                                          params={"m": m, "own": round(mine_share, 4), "peer_p50": round(p50, 4),
                                                  "peers_n": len(vals)},
                                          n=int(stats["cust_txns"]), period="کل بازه داده",
                                          extra={"note_fa": "رفتار بازگشت در کل شش‌ماهه سنجیده می‌شود تا دوره‌های کوتاه گمراه‌کننده نباشند."})],
                })

    # 7) customer concentration risk
    conc = q1("""
        WITH pc AS (SELECT payer_card_key, sum(amount) AS g FROM sessions
                    WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='verified' GROUP BY 1),
        r AS (SELECT g, row_number() OVER (ORDER BY g DESC) AS rk FROM pc)
        SELECT coalesce(sum(g) FILTER (WHERE rk<=5),0)/nullif(sum(g),0) AS top5, count(*) AS n,
               coalesce(sum(g) FILTER (WHERE rk<=5),0) AS top5_gmv FROM r""", {"m": m, "f": f, "t": t})
    if (conc.get("n") or 0) >= MIN_CUSTOMERS_RETENTION and (conc.get("top5") or 0) > 0.4:
        cards.append({
            "id": "concentration", "kind": "concentration", "card_type": "alert",
            "title_fa": "وابستگی فروش به چند مشتری معدود",
            "observation_fa": f"۵ مشتری برتر {fa_pct(conc['top5'], 0)} از فروش موفق این دوره را ساخته‌اند ({fa_money(conc['top5_gmv'])}).",
            "diagnosis_fa": "از دست دادن یکی از این مشتریان ضربه بزرگی به درآمد می‌زند؛ این یک ریسک است، نه فرصت فوری.",
            "action_fa": "برای مشتریان کلیدی قرارداد/مشوق وفاداری تعریف کنید و هم‌زمان جذب مشتری جدید را تقویت کنید.",
            "impact_low": 0, "impact_high": 0,
            "impact_label_fa": f"فروش در معرض ریسک: {fa_money(conc['top5_gmv'])}",
            "confidence": "high", "effort": "hard", "n": int(conc["n"]),
            "risk_gmv": conc["top5_gmv"],
            "evidence": [evidence("customer_concentration",
                                  sql="SELECT sum(g) FILTER (rk<=5)/sum(g) FROM (per-card GMV ranked) WHERE merchant/period",
                                  params={"m": m, "f": f, "t": t}, n=int(conc["n"]), period=_fmt_period(f, t))],
        })

    # 8) PSP friction — names the specific weak gateway from data the funnel already computes
    if me["sessions"] >= MIN_SESSIONS_INSIGHT:
        c = _psp_card(m, f, t)
        if c:
            cards.append(c)

    # 9) GMV change alert (last two halves of the selected period)
    ch = _change_alert(m, f, t)
    if ch:
        cards.append(ch)

    # Ranking. Opportunities (recoverable rial) ALWAYS rank above alerts (risks/context with
    # no recoverable figure) — a zero-impact "sales grew" alert must never outrank real money.
    for c in cards:
        c.setdefault("card_type", "opportunity")
        if c["card_type"] == "opportunity":
            base = c["impact_high"] or 0
            c["score"] = round(base * CONF_W[c["confidence"]] / EFFORT_W[c["effort"]])
        else:
            c["score"] = 0  # alerts are ordered after opportunities, by their own magnitude
    cards.sort(key=lambda c: (
        0 if c["card_type"] == "opportunity" else 1,   # opportunities first
        -c["score"] if c["card_type"] == "opportunity" else -c.get("risk_gmv", 0),
        c["id"],
    ))
    return cards


def _psp_card(m: str, f: str, t: str) -> dict | None:
    """Actionable PSP-routing insight from within-merchant attempt success rates."""
    from .db import q
    rows = q("""
        SELECT psp_code, count(*) AS attempts, avg(ok::int) AS ok_rate
        FROM attempts WHERE merchant_key=$m AND d BETWEEN $f AND $t AND psp_code IS NOT NULL
        GROUP BY psp_code HAVING count(*) >= 200 ORDER BY ok_rate""", {"m": m, "f": f, "t": t})
    rows = [r for r in rows if r["ok_rate"] is not None]
    if len(rows) < 2:
        return None
    worst, best = rows[0], rows[-1]
    gap = best["ok_rate"] - worst["ok_rate"]
    if gap < 0.10:  # gateways perform similarly → no routing lever
        return None
    codes = q("""
        SELECT switch_response_code AS code, count(*) AS n FROM attempts
        WHERE merchant_key=$m AND d BETWEEN $f AND $t AND psp_code=$p AND NOT ok
              AND switch_response_code IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 3""", {"m": m, "f": f, "t": t, "p": worst["psp_code"]})
    code_txt = ("؛ پرتکرارترین کدهای خطا: " + "، ".join(c["code"] for c in codes)) if codes else ""
    lost = round(worst["attempts"] * gap * 0.5)  # attempts that a better PSP might have converted
    return {
        "id": "psp_friction", "kind": "psp_friction", "card_type": "opportunity",
        "title_fa": f"درگاه {worst['psp_code']} به‌طور محسوس ضعیف‌تر از بقیه عمل می‌کند",
        "observation_fa": (f"نرخ موفقیت تلاش‌ها روی {worst['psp_code']} برابر {fa_pct(worst['ok_rate'])} است "
                           f"(روی {fa_num(worst['attempts'])} تلاش)، در حالی که {best['psp_code']} برای همین "
                           f"فروشگاه {fa_pct(best['ok_rate'])} موفقیت دارد — اختلاف {fa_digits(f'{gap*100:.0f}')} واحد درصد{code_txt}."),
        "diagnosis_fa": "این مقایسه فقط روی ترافیک خود شماست؛ انتخاب درگاه سمت زرین‌پال انجام می‌شود، اما الگوی ضعف پایدار است.",
        "action_fa": f"از پشتیبانی زرین‌پال بخواهید سهم ترافیک را از {worst['psp_code']} به درگاه قوی‌تر منتقل کند و کدهای خطای پرتکرار را بررسی کنید.",
        "impact_low": round(lost * 0.5), "impact_high": lost,
        "impact_label_fa": "برآورد تلاش‌های قابل نجات با مسیردهی به درگاه بهتر (تعداد تراکنش)",
        "impact_is_count": True,
        "confidence": "medium" if worst["attempts"] >= 1000 else "low", "effort": "easy",
        "n": int(worst["attempts"]),
        "evidence": [evidence("first_try_conv",
                              sql=("SELECT psp_code, count(*) attempts, avg(ok::int) ok_rate\n"
                                   "FROM attempts WHERE merchant_key=$m AND d BETWEEN $f AND $t\n"
                                   "  AND psp_code IS NOT NULL\n"
                                   "GROUP BY psp_code HAVING count(*) >= 200 ORDER BY ok_rate;"),
                              params={"m": m, "f": f, "t": t,
                                      "worst_psp": worst["psp_code"], "worst_rate": round(worst["ok_rate"], 4),
                                      "best_psp": best["psp_code"], "best_rate": round(best["ok_rate"], 4)},
                              n=int(worst["attempts"]), period=_fmt_period(f, t),
                              extra={"note_fa": "برآورد نجات = تلاش‌های درگاه ضعیف × شکاف نرخ × ۰٫۵ (سهم محافظه‌کارانه‌ای که با درگاه بهتر موفق می‌شد)."})],
    }


def __peer_repeat(keys: list[str]) -> list[dict]:
    from .db import q
    return q("SELECT repeat_txns, cust_txns FROM merchant_stats WHERE merchant_key IN (SELECT unnest($k::varchar[]))",
             {"k": keys})


def _change_alert(m: str, f: str, t: str) -> dict | None:
    from datetime import date, timedelta
    d1, d2 = date.fromisoformat(f), date.fromisoformat(t)
    if (d2 - d1).days < 27:
        return None
    mid = d1 + (d2 - d1) / 2
    ch = changes(m, f, str(mid), str(mid + timedelta(days=1)), t)
    if not ch["decomposable"] or not ch["before"]["gmv"]:
        return None
    rel = ch["delta_gmv"] / ch["before"]["gmv"]
    if abs(rel) < 0.10:
        return None
    contrib = ch["contrib"]
    driver_key = max(contrib, key=lambda k: abs(contrib[k]))
    names = {"sessions": "تعداد جلسه‌های پرداخت", "conv": "نرخ تبدیل", "ticket": "مبلغ متوسط تراکنش"}
    direction = "رشد" if rel > 0 else "افت"
    return {
        "id": "gmv_change", "kind": "gmv_change", "card_type": "alert",
        "title_fa": f"{direction} {fa_pct(abs(rel), 0)} فروش در نیمه دوم دوره",
        "observation_fa": f"فروش موفق از {fa_money(ch['before']['gmv'])} به {fa_money(ch['after']['gmv'])} رسید.",
        # plain-cause on the card face; the method name (LMDI) lives in the evidence drawer only
        "diagnosis_fa": f"بیشترین دلیل این تغییر «{names[driver_key]}» بوده است ({fa_money(contrib[driver_key])} از کل تغییر {fa_money(ch['delta_gmv'])}).",
        "action_fa": "جزئیات و سهم دقیق هر عامل را در صفحه «چه چیزی تغییر کرد؟» ببینید.",
        "impact_low": 0, "impact_high": 0,
        "impact_label_fa": f"تغییر کل فروش: {fa_money(ch['delta_gmv'])}",
        "confidence": "high", "effort": "easy", "n": int(ch["before"]["sessions"] + ch["after"]["sessions"]),
        "risk_gmv": abs(ch["delta_gmv"]),
        "evidence": [ch["evidence"]],
    }
