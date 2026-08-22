"""Control Center aggregations — platform / performance / AI-ops / sources.

Platform figures come from the same marts and the same session-grain discipline as
the merchant surface (one shared semantic layer). Performance and AI-Ops read live
telemetry; nothing here is fabricated — an empty telemetry ring yields has_data=False.
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import obs
from .ai import telemetry as ai_telemetry
from .config import MARTS_DIR
from .db import q, q1
from .fa import fa_num, fa_pct
from .sources import registry


@lru_cache(maxsize=1)
def _dq_sidecar() -> dict | None:
    """Pipeline-computed anomaly artifact (zarin/pipeline.py:build). None if a mart
    dir predates it — callers must fall back to a live query (ZB-025)."""
    p = MARTS_DIR / "data_quality.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# The marts are immutable for the life of the process, so platform/merchants/sources are
# pure functions of their arguments — the window picker only ever asks for a handful of
# distinct windows, and each one costs a full-platform scan of 2.06M sessions. Callers
# treat the result as read-only (verified: every call site serialises it and returns).
@lru_cache(maxsize=32)
def platform(f: str, t: str) -> dict:
    total_merchants = q1("SELECT count(*) AS n FROM merchant_stats")["n"]
    agg = q1("""
        SELECT count(DISTINCT merchant_key) AS active_merchants,
               count(*) AS sessions,
               count(*) FILTER (WHERE outcome='verified') AS verified,
               sum(amount) FILTER (WHERE outcome='verified') AS gmv,
               count(*) FILTER (WHERE outcome='paid_unverified') AS paid_unverified,
               sum(amount) FILTER (WHERE outcome='paid_unverified') AS paid_unverified_amount,
               count(*) FILTER (WHERE outcome='no_attempt') AS no_attempt,
               count(*) FILTER (WHERE recovered) AS recovered,
               sum(amount) FILTER (WHERE recovered) AS recovered_gmv
        FROM sessions WHERE d BETWEEN $f AND $t""", {"f": f, "t": t})
    sessions = agg.get("sessions") or 0
    verified = agg.get("verified") or 0
    no_attempt = agg.get("no_attempt") or 0

    categories = q("""
        SELECT ms.category_title AS category,
               count(DISTINCT s.merchant_key) AS merchants,
               count(*) AS sessions,
               sum(s.amount) FILTER (WHERE s.outcome='verified') AS gmv
        FROM sessions s JOIN merchant_stats ms USING(merchant_key)
        WHERE s.d BETWEEN $f AND $t
        GROUP BY 1 ORDER BY gmv DESC NULLS LAST, category LIMIT 10""", {"f": f, "t": t})

    conc = q1("""
        WITH g AS (SELECT merchant_key, sum(amount) FILTER (WHERE outcome='verified') AS gmv
                   FROM sessions WHERE d BETWEEN $f AND $t GROUP BY 1),
             -- merchant_key breaks GMV ties so the "top 5" set is stable between runs
             r AS (SELECT gmv, row_number() OVER (ORDER BY gmv DESC NULLS LAST, merchant_key) AS rk FROM g)
        SELECT sum(gmv) FILTER (WHERE rk<=5)/nullif(sum(gmv),0) AS top5, count(*) AS n FROM r""",
        {"f": f, "t": t})

    kpis = {
        "total_merchants": total_merchants,
        "active_merchants": agg.get("active_merchants") or 0,
        "sessions": sessions, "verified": verified,
        "gmv": agg.get("gmv") or 0,
        "conv": (verified / sessions) if sessions else None,
        "no_attempt_rate": (no_attempt / sessions) if sessions else None,
        "paid_unverified": agg.get("paid_unverified") or 0,
        "paid_unverified_amount": agg.get("paid_unverified_amount") or 0,
        "recovered": agg.get("recovered") or 0,
        "recovered_gmv": agg.get("recovered_gmv") or 0,
    }

    # window-scoped to match the KPIs' grain (an all-time count next to windowed KPIs misleads)
    anomalies = _windowed_anomalies(f, t)

    return {
        "period": {"from": f, "to": t},
        "kpis": kpis,
        "categories": categories,
        "concentration": {"top5_share": conc.get("top5"), "n_merchants": conc.get("n")},
        "anomalies": anomalies,
        "insights": _platform_insights(kpis, conc),
    }


def _windowed_anomalies(f: str, t: str) -> dict:
    """reversed_sessions + verified_wo_ok_try, scoped to [f, t]. Prefers the pipeline
    sidecar (Python-filters a ~dozens-of-rows list) over the live correlated subquery
    that used to re-aggregate all 1.95M attempt rows on every call (ZB-025)."""
    dq = _dq_sidecar()
    if dq is not None:
        wo_ok = sum(1 for s in dq["bad_sessions"] if s["wo_ok_try"] and f <= s["d"] <= t)
        reversed_sessions = q1(
            "SELECT count(*) AS n FROM sessions WHERE outcome='reversed' AND d BETWEEN $f AND $t",
            {"f": f, "t": t})["n"]
        return {"reversed_sessions": reversed_sessions, "verified_wo_ok_try": wo_ok}
    return q1("""SELECT
        (SELECT count(*) FROM sessions WHERE outcome='reversed' AND d BETWEEN $f AND $t) AS reversed_sessions,
        (SELECT count(*) FROM sessions WHERE session_status='Verified' AND outcome='verified'
           AND d BETWEEN $f AND $t
           AND session_key IN (SELECT session_key FROM attempts GROUP BY 1 HAVING sum(ok::int)=0)) AS verified_wo_ok_try""",
        {"f": f, "t": t})


_MERCHANT_SORT = {
    "unverified": "w.paid_unverified_amount DESC",
    "no_attempt": "no_attempt_rate DESC NULLS LAST",
    "gmv": "w.gmv DESC NULLS LAST",
    "recovered": "w.recovered_gmv DESC",
}


@lru_cache(maxsize=64)
def merchants(sort: str, limit: int, f: str, t: str) -> dict:
    """Merchant-level drilldown behind the Control Center's recommended actions (ZB-026).

    WINDOWED. This read `merchant_stats`, which is lifetime, while the page around it carries
    the operator's selected period and `platform(f, t)` beside it is windowed — so picking
    "last 30 days" changed every KPI on the screen and none of the rows in the table, and the
    table's own numbers could not be reconciled with the totals directly above them. The
    aggregation now comes from the same session rows over the same window as everything else
    on the page.
    """
    order = _MERCHANT_SORT.get(sort, _MERCHANT_SORT["unverified"])
    rows = q(f"""
        WITH w AS (
            SELECT merchant_key,
                   count(*) AS sessions,
                   sum(amount) FILTER (WHERE outcome='verified') AS gmv,
                   count(*) FILTER (WHERE outcome='paid_unverified') AS paid_unverified,
                   coalesce(sum(amount) FILTER (WHERE outcome='paid_unverified'), 0)
                       AS paid_unverified_amount,
                   count(*) FILTER (WHERE outcome='no_attempt') AS no_attempt,
                   coalesce(sum(amount) FILTER (WHERE recovered AND outcome='verified'), 0)
                       AS recovered_gmv
            FROM sessions WHERE d BETWEEN $f AND $t GROUP BY 1
        )
        SELECT w.merchant_key, ms.category_title, w.sessions, w.gmv,
               w.paid_unverified_amount, w.paid_unverified,
               w.no_attempt / nullif(w.sessions, 0) AS no_attempt_rate,
               w.recovered_gmv
        FROM w JOIN merchant_stats ms USING (merchant_key)
        -- merchant_key breaks ties so the table is the same table between identical calls
        ORDER BY {order}, w.merchant_key
        LIMIT {int(limit)}""", {"f": f, "t": t})
    return {"rows": rows, "period": {"from": f, "to": t}}


def _platform_insights(k: dict, conc: dict) -> list[dict]:
    out = []
    if k["paid_unverified_amount"]:
        out.append({"severity": "high",
                    "title_fa": "پول تسویه‌شده اما تاییدنشده در کل پلتفرم",
                    "body_fa": f"{fa_num(k['paid_unverified'])} پرداخت در بانک تسویه شده اما پذیرنده تایید نکرده است.",
                    "action_fa": "پذیرندگان دارای بیشترین مبلغ تاییدنشده را برای فعال‌سازی وریفای خودکار در اولویت بگذارید."})
    top5 = conc.get("top5") or 0
    if top5 >= 0.5:
        out.append({"severity": "medium",
                    "title_fa": "تمرکز درآمد پلتفرم",
                    "body_fa": f"۵ پذیرنده برتر {fa_pct(top5, 0)} از فروش موفق را می‌سازند.",
                    "action_fa": "ریسک تمرکز؛ سلامت و نگه‌داشت این پذیرندگان کلیدی را جدا پایش کنید."})
    if k["no_attempt_rate"] and k["no_attempt_rate"] >= 0.2:
        out.append({"severity": "medium",
                    "title_fa": "انصراف پیش از پرداخت در سطح پلتفرم",
                    "body_fa": f"{fa_pct(k['no_attempt_rate'], 0)} جلسه‌ها اصلاً به درگاه نرسیدند (NoAttempt).",
                    "action_fa": "تجربه پیش از درگاه (ریدایرکت/بارگذاری صفحه پرداخت) را بررسی کنید."})
    return out


def performance() -> dict:
    return obs.summary()


def ai_ops() -> dict:
    return ai_telemetry.summary()


@lru_cache(maxsize=8)
def sources(f: str, t: str) -> dict:
    statuses = [a.status().to_dict() for a in registry()]
    # Cross-source (traffic→payment) insights require a connected web-analytics source
    # AND two aligned time windows (see zarin.sources.insights.cross_source). Until GA4 is
    # connected, we report an honest empty set rather than a fabricated relationship.
    web_connected = any(s["connected"] and s["kind"] == "web_analytics" for s in statuses)
    note = None if web_connected else "برای بینش‌های میان‌منبعی (ترافیک→پرداخت) ابتدا یک منبع تحلیل وب مانند GA4 را متصل کنید."
    return {"sources": statuses, "cross_source_insights": [], "cross_source_note_fa": note}
