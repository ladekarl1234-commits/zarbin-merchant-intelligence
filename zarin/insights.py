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


def _gap_card(*, kind, me, peers_rates, rate_key, f, t, title_fa, diagnosis_fa, action_fa,
              effort, metric_id, extra_note=None):
    """Shared shape for 'your loss-rate exceeds peer baseline' opportunities."""
    mine = me.get(rate_key)
    vals = sorted(v[rate_key] for v in peers_rates if v.get(rate_key) is not None)
    if mine is None or len(vals) < 5:
        return None
    p50, p25 = _quantile(vals, 0.5), _quantile(vals, 0.25)
    gap_mid, gap_hi = mine - p50, mine - p25
    if gap_mid < 0.02:  # less than 2pp worse than peer median → not worth a card
        return None
    sessions = me["sessions"]
    conv_of_attempted = (me["verified"] / me["attempted"]) if me["attempted"] else 0
    ticket = q1("SELECT quantile_cont(amount,0.5) AS v FROM sessions "
                "WHERE merchant_key=$m AND d BETWEEN $f AND $t AND outcome='verified'",
                {"m": me["m"], "f": f, "t": t})["v"] or 0
    lo = gap_mid * sessions * conv_of_attempted * ticket
    hi = max(gap_hi, gap_mid) * sessions * conv_of_attempted * ticket
    if hi <= 0:
        return None
    conf = _conf(sessions, len(vals))
    return {
        "id": f"{kind}", "kind": kind,
        "title_fa": title_fa,
        "observation_fa": f"نرخ شما {mine*100:.1f}٪ است؛ میانه همتایان {p50*100:.1f}٪ (اختلاف {gap_mid*100:.1f} واحد درصد).",
        "diagnosis_fa": diagnosis_fa,
        "action_fa": action_fa,
        "impact_low": round(min(lo, hi)), "impact_high": round(max(lo, hi)),
        "impact_label_fa": "برآورد فرصت قابل بازیابی در این دوره",
        "confidence": conf, "effort": effort,
        "n": int(sessions),
        "evidence": [evidence(metric_id,
                              sql="rate = per registry; baseline = quantiles of same-period peer rates (merchant_daily)",
                              params={"m": me["m"], "f": f, "t": t, "peers_n": len(vals),
                                      "peer_p50": round(p50, 4), "peer_p25": round(p25, 4),
                                      "own_rate": round(mine, 4), "conv_of_attempted": round(conv_of_attempted, 4),
                                      "median_ticket": ticket},
                              n=int(sessions), period=_fmt_period(f, t),
                              extra={"note_fa": extra_note or
                                     "فرصت = شکاف نرخ × جلسه‌های دوره × نرخ تبدیل تلاش‌های خود شما × میانه تیکت خود شما. کف بازه از میانه همتایان و سقف از چارک برتر ساخته می‌شود."}),
                     evidence("opportunity", sql="", params={})],
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
            "id": "paid_unverified", "kind": "paid_unverified",
            "title_fa": "پرداخت‌های تاییدنشده — پول رسیده اما تایید نشده",
            "observation_fa": f"{n:,} پرداخت به مبلغ {amt:,.0f} ریال در این دوره تسویه بانکی شده اما هرگز Verify نشده است.",
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
                        "id": "recovery_gap", "kind": "recovery_gap",
                        "title_fa": "تلاش مجدد کمتر از همتایان به نتیجه می‌رسد",
                        "observation_fa": f"از {fp:,.0f} جلسه‌ای که تلاش اولشان ناموفق بود فقط {mine_rr*100:.1f}٪ نجات یافت؛ میانه همتایان {p50*100:.1f}٪.",
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
                    "id": "high_value_friction", "kind": "high_value_friction",
                    "title_fa": "پرداخت‌های گران‌قیمت بیشتر شکست می‌خورند",
                    "observation_fa": f"نرخ تبدیل پنجک بالای مبلغ {hv['conv_top']*100:.1f}٪ است؛ {gap*100:.1f} واحد درصد کمتر از مبالغ میانی خودتان.",
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
                    "id": "repeat_gap", "kind": "repeat_gap",
                    "title_fa": "مشتریان کمتر از همتایان برمی‌گردند",
                    "observation_fa": f"{mine_share*100:.1f}٪ از پرداخت‌های موفق شما از مشتریان تکراری است؛ میانه همتایان {p50*100:.1f}٪.",
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
            "id": "concentration", "kind": "concentration",
            "title_fa": "وابستگی فروش به چند مشتری معدود",
            "observation_fa": f"۵ مشتری برتر {conc['top5']*100:.0f}٪ از فروش موفق این دوره را ساخته‌اند ({conc['top5_gmv']:,.0f} ریال).",
            "diagnosis_fa": "از دست دادن یکی از این مشتریان ضربه بزرگی به درآمد می‌زند؛ این یک ریسک است، نه فرصت فوری.",
            "action_fa": "برای مشتریان کلیدی قرارداد/مشوق وفاداری تعریف کنید و هم‌زمان جذب مشتری جدید را تقویت کنید.",
            "impact_low": 0, "impact_high": 0,
            "impact_label_fa": f"فروش در معرض ریسک: {conc['top5_gmv']:,.0f} ریال",
            "confidence": "high", "effort": "hard", "n": int(conc["n"]),
            "risk_gmv": conc["top5_gmv"],
            "evidence": [evidence("customer_concentration",
                                  sql="SELECT sum(g) FILTER (rk<=5)/sum(g) FROM (per-card GMV ranked) WHERE merchant/period",
                                  params={"m": m, "f": f, "t": t}, n=int(conc["n"]), period=_fmt_period(f, t))],
        })

    # 8) GMV change alert (last two halves of the selected period)
    ch = _change_alert(m, f, t)
    if ch:
        cards.append(ch)

    for c in cards:
        base = c["impact_high"] or c.get("risk_gmv", 0) or 0
        c["score"] = round(base * CONF_W[c["confidence"]] / EFFORT_W[c["effort"]])
    cards.sort(key=lambda c: (-c["score"], c["id"]))
    return cards


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
        "id": "gmv_change", "kind": "gmv_change",
        "title_fa": f"{direction} {abs(rel)*100:.0f}٪ فروش در نیمه دوم دوره",
        "observation_fa": f"فروش از {ch['before']['gmv']:,.0f} به {ch['after']['gmv']:,.0f} ریال رسید.",
        "diagnosis_fa": f"تجزیه LMDI: بیشترین سهم از «{names[driver_key]}» است ({contrib[driver_key]:,.0f} ریال از کل تغییر {ch['delta_gmv']:,.0f} ریالی).",
        "action_fa": "جزئیات را در صفحه «چه چیزی تغییر کرد؟» ببینید؛ سهم هر عامل به‌صورت قطعی محاسبه شده است.",
        "impact_low": 0, "impact_high": 0,
        "impact_label_fa": f"تغییر کل: {ch['delta_gmv']:,.0f} ریال",
        "confidence": "high", "effort": "easy", "n": int(ch["before"]["sessions"] + ch["after"]["sessions"]),
        "risk_gmv": abs(ch["delta_gmv"]),
        "evidence": [ch["evidence"]],
    }
