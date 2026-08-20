"""FastAPI app: merchant analytics + operations/control-plane APIs + static frontend."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai_ops, analytics, connectors, insights, ops_telemetry, peers
from .config import CURRENCY_NOTE, CUSTOMER_SCOPE_CAVEAT, FEE_CAVEAT, STATIC_DIR
from .db import q, q1

app = FastAPI(title="Zarbin — زرین‌بین", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.middleware("http")(ops_telemetry.observe_http)


def _range() -> tuple[str, str]:
    r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
    return str(r["f"]), str(r["t"])


def _check_merchant(m: str) -> None:
    if not q1("SELECT 1 AS x FROM merchant_stats WHERE merchant_key=$m", {"m": m}):
        raise HTTPException(404, f"merchant {m} not found")


def _valid_date(s: str, field: str) -> str:
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise HTTPException(400, f"invalid date for {field}: {s!r} (expected YYYY-MM-DD)") from None


def _dates(m: str, f: str | None, t: str | None) -> tuple[str, str]:
    lo, hi = _range()
    return (_valid_date(f, "f") if f else lo, _valid_date(t, "t") if t else hi)


@app.get("/api/meta")
@lru_cache(maxsize=1)
def meta():
    lo, hi = _range()
    merchants = q("""
        SELECT merchant_key, category_title, sessions, verified, gmv, active_months
        FROM merchant_stats ORDER BY gmv DESC NULLS LAST""")
    ranks = q("""
        WITH s AS (SELECT merchant_key,
            gmv, paid_unverified_amount AS pua, repeat_txns,
            no_attempt / nullif(sessions,0) AS na_rate,
            recovered / nullif(sessions,0) AS rec_rate
          FROM merchant_stats WHERE sessions >= 5000)
        SELECT merchant_key,
               row_number() OVER (ORDER BY gmv DESC) AS r_gmv,
               row_number() OVER (ORDER BY pua DESC) AS r_pua,
               row_number() OVER (ORDER BY na_rate DESC) AS r_na,
               row_number() OVER (ORDER BY rec_rate DESC) AS r_rec,
               row_number() OVER (ORDER BY repeat_txns DESC) AS r_rep
        FROM s""")
    presets = [("بیشترین فروش موفق", "r_gmv"), ("بیشترین مبلغ پرداخت تاییدنشده", "r_pua"),
               ("بالاترین انصراف پیش از پرداخت", "r_na"), ("بیشترین نجات با تلاش مجدد", "r_rec"),
               ("بیشترین مشتری تکراری", "r_rep")]
    seen, demo_list = set(), []
    for why, col in presets:
        for row in sorted(ranks, key=lambda x: x[col]):
            if row["merchant_key"] not in seen:
                seen.add(row["merchant_key"])
                demo_list.append({"merchant_key": row["merchant_key"], "why": why})
                break
    return {"range": {"from": lo, "to": hi}, "merchants": merchants, "demo": demo_list,
            "notes": {"currency": CURRENCY_NOTE, "fee": FEE_CAVEAT, "customer": CUSTOMER_SCOPE_CAVEAT}}


@app.get("/api/overview")
def overview(m: str, f: str | None = None, t: str | None = None,
             cf: str | None = None, ct: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    cf = _valid_date(cf, "cf") if cf else None
    ct = _valid_date(ct, "ct") if ct else None
    return analytics.overview(m, f, t, cf, ct)


@app.get("/api/insights")
def get_insights(m: str, f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return {"cards": insights.generate(m, f, t)}


@app.get("/api/funnel")
def funnel(m: str, f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return analytics.funnel(m, f, t)


@app.get("/api/customers")
def customers(m: str, f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return analytics.customers(m, f, t)


@app.get("/api/peers")
def get_peers(m: str, f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return peers.benchmarks(m, f, t)


@app.get("/api/changes")
def changes(m: str, f1: str, t1: str, f2: str, t2: str):
    _check_merchant(m)
    f1, t1 = _valid_date(f1, "f1"), _valid_date(t1, "t1")
    f2, t2 = _valid_date(f2, "f2"), _valid_date(t2, "t2")
    return analytics.changes(m, f1, t1, f2, t2)


@app.get("/api/copilot")
def ask(m: str, q_: str = Query(alias="q", min_length=1, max_length=1200),
        f: str | None = None, t: str | None = None):
    """Merchant copilot. Analytics are deterministic; OpenRouter is an optional explanation layer."""
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return ai_ops.answer(m, q_, f, t)


def _admin_snapshot() -> dict:
    lo, hi = _range()
    totals = q1("""
        SELECT count(*) AS sessions,
               sum((outcome='verified')::int) AS verified,
               sum(amount) FILTER (WHERE outcome='verified') AS gmv,
               count(DISTINCT merchant_key) AS merchants,
               avg(n_tries) AS avg_tries
        FROM sessions""")
    data_quality = q1("""
        SELECT
          sum((outcome='paid_unverified')::int) AS paid_unverified,
          sum((outcome='no_attempt')::int) AS no_attempt,
          sum((outcome='reversed')::int) AS reversed
        FROM sessions""")
    return {
        "period": {"from": lo, "to": hi},
        "platform": totals,
        "data_quality": data_quality,
        "api": ops_telemetry.stats(),
        "ai": ai_ops.stats(),
        "sources": connectors.source_statuses(),
        "ga4": connectors.ga4_snapshot(),
        "source_insights": connectors.ga4_insights(),
        "slo": {
            "target_api_p95_ms": 1000,
            "target_ai_grounded_rate": 0.98,
            "target_ai_fallback_rate": 0.05,
            "target_success_rate": 0.99,
        },
    }


@app.get("/api/admin/ops")
def admin_ops():
    """Control-plane snapshot for business/technical operators."""
    return _admin_snapshot()


@app.get("/api/admin/copilot")
def admin_ask(q_: str = Query(alias="q", min_length=1, max_length=1200)):
    """Grounded operations copilot. It can only reason over current control-plane telemetry."""
    return ai_ops.admin_answer(q_, _admin_snapshot())


@app.post("/api/admin/ga4/sync")
def admin_ga4_sync(days: int = Query(28, ge=1, le=365)):
    try:
        return connectors.sync_ga4(days)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


_VALID_OUTCOMES = {"verified", "paid_unverified", "no_attempt", "abandoned_inbank", "failed_bank", "reversed"}


@app.get("/api/evidence/sessions")
def evidence_sessions(m: str, outcome: str | None = None, f: str | None = None,
                      t: str | None = None, limit: int = Query(12, ge=1, le=50)):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    if outcome is not None and outcome not in _VALID_OUTCOMES:
        raise HTTPException(400, f"unknown outcome: {outcome!r}")
    cond = "AND outcome = $o" if outcome else ""
    rows = q(f"""
        SELECT session_key, d, amount, outcome, n_tries, first_try_status, last_try_status,
               win_psp, session_status
        FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t {cond}
        ORDER BY amount DESC LIMIT {int(limit)}""",
        {"m": m, "f": f, "t": t, **({"o": outcome} if outcome else {})})
    total = q1(f"SELECT count(*) AS n FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t {cond}",
               {"m": m, "f": f, "t": t, **({"o": outcome} if outcome else {})})
    return {"rows": rows, "total": total["n"],
            "note_fa": "نمونه جلسه‌های منبع (به ترتیب مبلغ). session_key همان شناسه ردیف‌های دیتاست اصلی است."}


@app.get("/api/quality")
def quality():
    outcomes = q("SELECT outcome, count(*) AS n, sum(amount) AS amount FROM sessions GROUP BY 1 ORDER BY n DESC")
    conc = q1("""WITH g AS (SELECT merchant_key, sum(gmv) AS gmv FROM merchant_daily GROUP BY 1),
                 r AS (SELECT gmv, row_number() OVER (ORDER BY gmv DESC) AS rk FROM g)
                 SELECT sum(gmv) FILTER (WHERE rk<=5)/sum(gmv) AS top5, count(*) AS n FROM r""")
    anomalies = q1("""SELECT
        (SELECT count(*) FROM sessions WHERE session_status='Verified' AND outcome='verified'
           AND session_key IN (SELECT session_key FROM attempts GROUP BY 1 HAVING sum(ok::int)=0)) AS verified_wo_ok_try,
        (SELECT count(*) FROM sessions WHERE outcome='reversed') AS reversed_sessions""")
    return {
        "outcomes": outcomes, "concentration": conc, "anomalies": anomalies,
        "rules_fa": [
            "هر ردیف دیتاست یک «تلاش پرداخت» است؛ همه متریک‌ها روی سطح «جلسه» محاسبه می‌شوند تا تلاش‌های تکراری چیزی را چند بار نشمارند.",
            "NoAttempt یعنی پرداخت‌کننده هرگز به درگاه نرسید؛ این حالت از خطای بانکی جداست.",
            "موفقیت = جلسه تایید نهایی‌شده. جلسه‌های Paid تسویه شده‌اند اما تایید پذیرنده ندارند و جدا گزارش می‌شوند.",
            "شناسه کارت فقط در تلاش‌های به سرانجام رسیده ثبت شده و بین پذیرنده‌ها مشترک نیست؛ تحلیل مشتری فقط پرداخت‌کنندگان موفق همان پذیرنده است.",
            FEE_CAVEAT,
            "اختلاف چندثانیه‌ای ساعت بین created_at و try_created_at دست‌نخورده باقی مانده است.",
            "۲۸ جلسه Verified بدون تلاش Verified و ۱ جلسه Reversed در داده وجود دارد؛ اصلاح نشده‌اند و مستند شده‌اند.",
            CURRENCY_NOTE,
        ],
    }


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    _STATIC_BASE = STATIC_DIR.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = Path(os.path.normpath(_STATIC_BASE / path))
        if path and f.is_relative_to(_STATIC_BASE) and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
