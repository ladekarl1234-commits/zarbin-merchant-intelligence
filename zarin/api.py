"""FastAPI app: /api/* JSON endpoints + static frontend."""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, copilot, insights, peers
from .config import CURRENCY_NOTE, CUSTOMER_SCOPE_CAVEAT, FEE_CAVEAT, STATIC_DIR
from .db import q, q1

app = FastAPI(title="Zarbin — زرین‌بین", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _range() -> tuple[str, str]:
    r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
    return str(r["f"]), str(r["t"])


def _check_merchant(m: str) -> None:
    if not q1("SELECT 1 AS x FROM merchant_stats WHERE merchant_key=$m", {"m": m}):
        raise HTTPException(404, f"merchant {m} not found")


def _dates(m: str, f: str | None, t: str | None) -> tuple[str, str]:
    lo, hi = _range()
    return (f or lo, t or hi)


@app.get("/api/meta")
@lru_cache(maxsize=1)
def meta():
    lo, hi = _range()
    merchants = q("""
        SELECT merchant_key, category_title, sessions, verified, gmv, active_months
        FROM merchant_stats ORDER BY gmv DESC NULLS LAST""")
    # demo presets are selected programmatically, not hardcoded conclusions:
    demo = q("""
        WITH s AS (SELECT *,
            paid_unverified_amount AS pua,
            no_attempt / nullif(sessions,0) AS na_rate,
            recovered / nullif(sessions,0) AS rec_rate
          FROM merchant_stats WHERE sessions >= 5000)
        SELECT * FROM (
          (SELECT merchant_key, 'بیشترین فروش موفق' AS why FROM s ORDER BY gmv DESC LIMIT 1)
          UNION ALL
          (SELECT merchant_key, 'بیشترین مبلغ پرداخت تاییدنشده' FROM s ORDER BY pua DESC LIMIT 1)
          UNION ALL
          (SELECT merchant_key, 'بالاترین انصراف پیش از پرداخت' FROM s ORDER BY na_rate DESC LIMIT 1)
          UNION ALL
          (SELECT merchant_key, 'بیشترین نجات با تلاش مجدد' FROM s ORDER BY rec_rate DESC LIMIT 1)
          UNION ALL
          (SELECT merchant_key, 'بیشترین مشتری تکراری' FROM s ORDER BY repeat_txns DESC LIMIT 1))
        """)
    seen, demo_list = set(), []
    for d in demo:
        if d["merchant_key"] not in seen:
            seen.add(d["merchant_key"])
            demo_list.append(d)
    return {"range": {"from": lo, "to": hi}, "merchants": merchants, "demo": demo_list,
            "notes": {"currency": CURRENCY_NOTE, "fee": FEE_CAVEAT, "customer": CUSTOMER_SCOPE_CAVEAT}}


@app.get("/api/overview")
def overview(m: str, f: str | None = None, t: str | None = None,
             cf: str | None = None, ct: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
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
    return analytics.changes(m, f1, t1, f2, t2)


@app.get("/api/copilot")
def ask(m: str, q_: str = Query(alias="q"), f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return copilot.answer(m, q_, f, t)


@app.get("/api/evidence/sessions")
def evidence_sessions(m: str, outcome: str | None = None, f: str | None = None,
                      t: str | None = None, limit: int = 12):
    """Drill-through: sample source sessions behind a metric."""
    _check_merchant(m)
    f, t = _dates(m, f, t)
    cond = "AND outcome = $o" if outcome else ""
    rows = q(f"""
        SELECT session_key, d, amount, outcome, n_tries, first_try_status, last_try_status,
               win_psp, session_status
        FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t {cond}
        ORDER BY amount DESC LIMIT {min(int(limit), 50)}""",
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
            "NoAttempt (try_seq=0) یعنی پرداخت‌کننده هرگز به درگاه نرسید؛ این حالت از خطای بانکی جداست.",
            "موفقیت = جلسه Verified. جلسه‌های Paid تسویه شده‌اند اما تایید پذیرنده ندارند و جدا گزارش می‌شوند.",
            "شناسه کارت فقط در تلاش‌های به سرانجام رسیده ثبت شده و بین پذیرنده‌ها مشترک نیست؛ تحلیل مشتری فقط پرداخت‌کنندگان موفق همان پذیرنده است.",
            FEE_CAVEAT,
            "اختلاف چندثانیه‌ای ساعت بین created_at و try_created_at (جیتر ساعت سرور) دست‌نخورده باقی مانده است.",
            "۲۸ جلسه Verified بدون تلاش Verified و ۱ جلسه Reversed در داده وجود دارد؛ اصلاح نشده‌اند و مستند شده‌اند.",
            CURRENCY_NOTE,
        ],
    }


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
