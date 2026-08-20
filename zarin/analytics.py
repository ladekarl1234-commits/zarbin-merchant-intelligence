"""Merchant analytics. Every public function returns values + evidence payloads
built from the metric registry, so the UI can always answer «این عدد از کجا آمد؟».

All queries are session-grain (marts) — attempt rows can never inflate counts here.
"""
from __future__ import annotations

import math

from .config import MIN_SEGMENT_N
from .db import q, q1
from .registry import evidence

PERIOD_SQL = "merchant_key = $m AND d BETWEEN $f AND $t"


def _period(f: str, t: str) -> str:
    return f"{f} تا {t}"


# ---------------------------------------------------------------- overview ---

_AGG_SQL = f"""
SELECT coalesce(sum(sessions),0) AS sessions, coalesce(sum(attempted),0) AS attempted,
       coalesce(sum(verified),0) AS verified, coalesce(sum(no_attempt),0) AS no_attempt,
       coalesce(sum(abandoned_inbank),0) AS abandoned_inbank, coalesce(sum(failed_bank),0) AS failed_bank,
       coalesce(sum(paid_unverified),0) AS paid_unverified, coalesce(sum(paid_unverified_amount),0) AS paid_unverified_amount,
       coalesce(sum(reversed),0) AS reversed,
       coalesce(sum(recovered),0) AS recovered, coalesce(sum(first_try_ok),0) AS first_try_ok,
       coalesce(sum(first_try_verified),0) AS first_try_verified,
       coalesce(sum(gmv),0) AS gmv, coalesce(sum(fee_index_sum),0) AS fee_index_sum
FROM merchant_daily WHERE {PERIOD_SQL}
"""


def period_agg(m: str, f: str, t: str) -> dict:
    r = q1(_AGG_SQL, {"m": m, "f": f, "t": t})
    s = r["sessions"] or 0
    r["conv"] = r["verified"] / s if s else None
    r["attempt_rate"] = r["attempted"] / s if s else None
    r["no_attempt_rate"] = r["no_attempt"] / s if s else None
    r["inbank_abandon_rate"] = r["abandoned_inbank"] / s if s else None
    r["failed_bank_rate"] = r["failed_bank"] / s if s else None
    # user-facing: first attempt led to a VERIFIED payment (Paid-first counts only for the recovery pool)
    r["first_try_conv"] = r["first_try_verified"] / s if s else None
    r["avg_ticket"] = r["gmv"] / r["verified"] if r["verified"] else None
    return r


def overview(m: str, f: str, t: str, cf: str | None, ct: str | None) -> dict:
    cur = period_agg(m, f, t)
    med = q1("SELECT quantile_cont(amount, 0.5) AS v FROM sessions "
             f"WHERE {PERIOD_SQL} AND outcome='verified'", {"m": m, "f": f, "t": t})["v"]
    cust = q1(f"""
        SELECT count(DISTINCT payer_card_key) AS customers
        FROM sessions WHERE {PERIOD_SQL} AND outcome='verified'""", {"m": m, "f": f, "t": t})
    daily = q(f"""
        SELECT d, sessions, verified, gmv,
               verified / nullif(sessions,0) AS conv
        FROM merchant_daily WHERE {PERIOD_SQL} ORDER BY d""", {"m": m, "f": f, "t": t})
    prev = period_agg(m, cf, ct) if cf and ct else None
    return {
        "period": {"from": f, "to": t},
        "compare": {"from": cf, "to": ct} if cf else None,
        "kpis": {
            "gmv": cur["gmv"], "verified": cur["verified"], "sessions": cur["sessions"],
            "conv": cur["conv"], "median_ticket": med, "customers": cust["customers"],
            "paid_unverified": cur["paid_unverified"],
            "paid_unverified_amount": cur["paid_unverified_amount"],
            "fee_index_sum": cur["fee_index_sum"],
        },
        "previous": {"gmv": prev["gmv"], "verified": prev["verified"], "sessions": prev["sessions"],
                     "conv": prev["conv"]} if prev else None,
        "daily": daily,
        "evidence": {
            "gmv": evidence("gmv", sql=_AGG_SQL, params={"m": m, "f": f, "t": t},
                            n=int(cur["verified"]), period=_period(f, t)),
            "conv": evidence("conv", sql=_AGG_SQL, params={"m": m, "f": f, "t": t},
                             n=int(cur["sessions"]), period=_period(f, t)),
            "median_ticket": evidence("median_ticket",
                                      sql=f"SELECT quantile_cont(amount,0.5) FROM sessions WHERE {PERIOD_SQL} AND outcome='verified'",
                                      params={"m": m, "f": f, "t": t}, n=int(cur["verified"]), period=_period(f, t)),
            "customers": evidence("customers",
                                  sql=f"SELECT count(DISTINCT payer_card_key) FROM sessions WHERE {PERIOD_SQL} AND outcome='verified'",
                                  params={"m": m, "f": f, "t": t}, n=int(cust["customers"] or 0), period=_period(f, t)),
            "paid_unverified": evidence("paid_unverified", sql=_AGG_SQL, params={"m": m, "f": f, "t": t},
                                        n=int(cur["paid_unverified"]), period=_period(f, t)),
        },
    }


# ------------------------------------------------------------------ funnel ---

def funnel(m: str, f: str, t: str) -> dict:
    p = {"m": m, "f": f, "t": t}
    agg = period_agg(m, f, t)
    settled = agg["verified"] + agg["paid_unverified"]
    first_fail_pool = agg["attempted"] - agg["first_try_ok"]
    recovery_rate = agg["recovered"] / first_fail_pool if first_fail_pool else None
    rec_gmv = q1(f"""SELECT coalesce(sum(amount),0) AS v FROM sessions
                     WHERE {PERIOD_SQL} AND recovered AND outcome='verified'""", p)["v"]

    hours = q(f"""SELECT hour, count(*) AS sessions,
                         count(*) FILTER (WHERE outcome='verified') AS verified
                  FROM sessions WHERE {PERIOD_SQL} GROUP BY hour ORDER BY hour""", p)

    bands_sql = f"""
        WITH b AS (
          SELECT amount, outcome, ntile(5) OVER (ORDER BY amount) AS band
          FROM sessions WHERE {PERIOD_SQL})
        SELECT band, min(amount) AS lo, max(amount) AS hi, count(*) AS sessions,
               count(*) FILTER (WHERE outcome='verified') / count(*) AS conv
        FROM b GROUP BY band ORDER BY band"""
    bands = q(bands_sql, p)
    bands = [b for b in bands if b["sessions"] >= MIN_SEGMENT_N]

    psp_sql = f"""
        SELECT psp_code, count(*) AS attempts, avg(ok::int) AS ok_rate
        FROM attempts WHERE {PERIOD_SQL}
        GROUP BY psp_code HAVING count(*) >= {MIN_SEGMENT_N} ORDER BY attempts DESC"""
    psp = q(psp_sql, p)

    fail_codes = q(f"""
        SELECT switch_response_code AS code, count(*) AS n
        FROM attempts WHERE {PERIOD_SQL} AND NOT ok AND switch_response_code IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 6""", p)

    return {
        "period": {"from": f, "to": t},
        "stages": [
            {"id": "created", "label_fa": "جلسه ایجاد شد", "n": agg["sessions"]},
            {"id": "attempted", "label_fa": "اقدام به پرداخت", "n": agg["attempted"]},
            {"id": "settled", "label_fa": "پول به بانک رسید", "n": settled},
            {"id": "verified", "label_fa": "تایید نهایی (Verified)", "n": agg["verified"]},
        ],
        # all six outcomes so the breakdown sums exactly to sessions (reversed is ~0 but real)
        "outcomes": {k: agg[k] for k in
                     ("verified", "paid_unverified", "no_attempt", "abandoned_inbank", "failed_bank", "reversed")},
        "rates": {k: agg[k] for k in
                  ("conv", "first_try_conv", "no_attempt_rate", "inbank_abandon_rate", "failed_bank_rate")},
        "recovery": {"first_fail_pool": first_fail_pool, "recovered": agg["recovered"],
                     "recovery_rate": recovery_rate, "recovered_gmv": rec_gmv},
        "hours": hours, "amount_bands": bands, "psp": psp, "fail_codes": fail_codes,
        "evidence": {
            "funnel": evidence("no_attempt_rate", sql=_AGG_SQL, params=p,
                               n=int(agg["sessions"]), period=_period(f, t)),
            "recovery": evidence("recovery_rate",
                                 sql=f"SELECT sum(recovered::int) / nullif(sum((attempted AND NOT first_try_ok)::int),0) FROM sessions WHERE {PERIOD_SQL}",
                                 params=p, n=int(first_fail_pool), period=_period(f, t)),
            "amount_bands": evidence("conv", sql=bands_sql, params=p,
                                     n=int(agg["sessions"]), period=_period(f, t),
                                     extra={"note_fa": "پنجک‌های مبلغ فقط از جلسه‌های همین پذیرنده ساخته می‌شوند تا اثر ترکیب پذیرنده‌ها حذف شود."}),
        },
    }


# --------------------------------------------------------------- customers ---

def customers(m: str, f: str, t: str) -> dict:
    p = {"m": m, "f": f, "t": t}
    base_sql = f"""
        WITH v AS (
          SELECT s.payer_card_key AS card, s.amount, s.created_at, c.first_ts, c.n_verified
          FROM sessions s JOIN customers c
            ON c.merchant_key = s.merchant_key AND c.payer_card_key = s.payer_card_key
          WHERE s.{PERIOD_SQL} AND s.outcome='verified')
        SELECT count(DISTINCT card) AS customers,
               count(DISTINCT card) FILTER (WHERE first_ts >= $f::date) AS new_customers,
               count(*) AS txns,
               count(*) FILTER (WHERE n_verified > 1) AS repeat_txns,
               sum(amount) AS gmv,
               coalesce(sum(amount) FILTER (WHERE n_verified > 1), 0) AS repeat_gmv,
               count(DISTINCT card) FILTER (WHERE n_verified > 1) AS repeat_customers
        FROM v"""
    b = q1(base_sql, p)

    conc_sql = f"""
        WITH pc AS (SELECT payer_card_key, sum(amount) AS g
                    FROM sessions WHERE {PERIOD_SQL} AND outcome='verified' GROUP BY 1),
        r AS (SELECT g, row_number() OVER (ORDER BY g DESC) AS rk FROM pc)
        SELECT coalesce(sum(g) FILTER (WHERE rk<=5),0) / nullif(sum(g),0) AS top5_share,
               count(*) AS n FROM r"""
    conc = q1(conc_sql, p)

    interval = q1("""
        WITH v AS (SELECT payer_card_key, created_at,
                          lag(created_at) OVER (PARTITION BY payer_card_key ORDER BY created_at) AS prev
                   FROM sessions WHERE merchant_key=$m AND outcome='verified')
        SELECT quantile_cont(epoch(created_at - prev)/86400.0, 0.5) AS median_days, count(*) AS n
        FROM v WHERE prev IS NOT NULL""", {"m": m})

    cohorts = q("""
        WITH act AS (
          SELECT c.first_month, s.month,
                 datediff('month', c.first_month, s.month) AS k,
                 s.payer_card_key AS card
          FROM sessions s JOIN customers c
            ON c.merchant_key = s.merchant_key AND c.payer_card_key = s.payer_card_key
          WHERE s.merchant_key=$m AND s.outcome='verified'),
        size AS (SELECT first_month, count(DISTINCT card) AS n0 FROM act WHERE k=0 GROUP BY 1)
        SELECT act.first_month, act.k, count(DISTINCT act.card) AS active, any_value(size.n0) AS cohort_size
        FROM act JOIN size USING (first_month)
        GROUP BY 1,2 ORDER BY 1,2""", {"m": m})

    dormant = q1("""
        SELECT count(*) AS n, coalesce(sum(gmv),0) AS gmv
        FROM customers WHERE merchant_key=$m AND n_verified >= 3
          AND last_ts < ($t::date - INTERVAL 30 DAY)""", {"m": m, "t": t})

    return {
        "period": {"from": f, "to": t},
        # NOTE: interval + cohorts are computed over the FULL data window on purpose
        # (retention needs the whole history); the UI labels them «کل بازه داده».
        "summary": b, "concentration": conc, "interval": interval,
        "cohorts": cohorts, "dormant": dormant,
        "evidence": {
            "repeat": evidence("repeat_txn_share", sql=base_sql, params=p,
                               n=int(b["txns"] or 0), period=_period(f, t)),
            "concentration": evidence("customer_concentration", sql=conc_sql, params=p,
                                      n=int(conc["n"] or 0), period=_period(f, t)),
            "customers": evidence("customers", sql=base_sql, params=p,
                                  n=int(b["customers"] or 0), period=_period(f, t)),
        },
    }


# ------------------------------------------------- what changed (LMDI) -------

def _lmdi_contrib(g1: float, g2: float, x1: float, x2: float) -> float:
    """Log-mean weighted contribution of factor x to ΔG. Exact: Σ contribs = G2-G1."""
    if g1 <= 0 or g2 <= 0 or x1 <= 0 or x2 <= 0:
        return 0.0
    L = (g2 - g1) / (math.log(g2) - math.log(g1)) if g2 != g1 else g2
    return L * math.log(x2 / x1)


def changes(m: str, f1: str, t1: str, f2: str, t2: str) -> dict:
    """Decompose GMV change from period1 (before) to period2 (after)."""
    a, b = period_agg(m, f1, t1), period_agg(m, f2, t2)

    def comp(r):
        return {"sessions": r["sessions"], "conv": r["conv"] or 0,
                "ticket": (r["gmv"] / r["verified"]) if r["verified"] else 0, "gmv": r["gmv"]}
    c1, c2 = comp(a), comp(b)
    delta = c2["gmv"] - c1["gmv"]
    decomposable = min(c1["gmv"], c2["gmv"]) > 0 and min(c1["sessions"], c2["sessions"]) > 0 \
        and min(c1["conv"], c2["conv"]) > 0 and min(c1["ticket"], c2["ticket"]) > 0
    contrib = {}
    if decomposable:
        contrib = {
            "sessions": _lmdi_contrib(c1["gmv"], c2["gmv"], c1["sessions"], c2["sessions"]),
            "conv": _lmdi_contrib(c1["gmv"], c2["gmv"], c1["conv"], c2["conv"]),
            "ticket": _lmdi_contrib(c1["gmv"], c2["gmv"], c1["ticket"], c2["ticket"]),
        }

    # conversion change root-cause. Identity: conv = 1 − (paid + no_attempt + inbank +
    # failed_bank + reversed)/sessions, so Δconv = −Σ Δ(each loss rate) EXACTLY, incl. reversed.
    conv_drivers = {
        k: -((b[k] or 0) - (a[k] or 0))
        for k in ("no_attempt_rate", "inbank_abandon_rate", "failed_bank_rate")
    } if a["sessions"] and b["sessions"] else {}
    if conv_drivers:
        for label, key in (("paid_unverified_rate", "paid_unverified"), ("reversed_rate", "reversed")):
            ra = (a[key] / a["sessions"]) if a["sessions"] else 0
            rb = (b[key] / b["sessions"]) if b["sessions"] else 0
            conv_drivers[label] = -(rb - ra)

    return {
        "before": {"from": f1, "to": t1, **c1},
        "after": {"from": f2, "to": t2, **c2},
        "delta_gmv": delta,
        "decomposable": decomposable,
        "contrib": contrib,
        "conv_drivers": conv_drivers,
        "evidence": evidence("gmv_decomposition", sql=_AGG_SQL,
                             params={"m": m, "periods": [f"{f1}..{t1}", f"{f2}..{t2}"]},
                             n=int(a["sessions"] + b["sessions"]),
                             period=f"{_period(f1, t1)} در برابر {_period(f2, t2)}",
                             extra={"method_fa": "روش شاخص میانگین لگاریتمی (LMDI): سهم هر عامل = L(G₂,G₁)·ln(x₂/x₁). مجموع سهم سه عامل دقیقاً برابر تغییر کل GMV است."}),
    }
