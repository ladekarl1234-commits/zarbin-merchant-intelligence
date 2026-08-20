"""FastAPI app: /api/* JSON endpoints + static frontend."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, control, copilot, insights, obs, ops_copilot, peers
from .ai import telemetry as ai_telemetry
from .ai.eval import run_eval
from .config import CURRENCY_NOTE, CUSTOMER_SCOPE_CAVEAT, FEE_CAVEAT, STATIC_DIR
from .db import q, q1

app = FastAPI(title="Zarbin — زرین‌بین", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.middleware("http")(obs.middleware)  # request telemetry → Control Center Product Performance


def _range() -> tuple[str, str]:
    r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
    return str(r["f"]), str(r["t"])


def _check_merchant(m: str) -> None:
    if not q1("SELECT 1 AS x FROM merchant_stats WHERE merchant_key=$m", {"m": m}):
        raise HTTPException(404, f"merchant {m} not found")


def _valid_date(s: str, field: str) -> str:
    try:
        # normalize to canonical YYYY-MM-DD: date.fromisoformat also accepts basic/week
        # forms (e.g. "20260101", "2026-W01-1") that DuckDB's date cast then rejects → 500.
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
    # demo presets are selected programmatically, not hardcoded conclusions. Each preset
    # takes the top merchant that isn't already used by an earlier preset, so a collision
    # (e.g. the top-GMV merchant is also the paid-unverified leader) never drops a preset.
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
    cf = _valid_date(cf, "cf") if cf else None   # comparison window is the same trust boundary
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
    # reassign the NORMALIZED dates (not just validate) so basic-form ISO like 20260101
    # reaches DuckDB as canonical YYYY-MM-DD instead of raising a 500 — mirrors _dates().
    f1, t1 = _valid_date(f1, "f1"), _valid_date(t1, "t1")
    f2, t2 = _valid_date(f2, "f2"), _valid_date(t2, "t2")
    return analytics.changes(m, f1, t1, f2, t2)


@app.get("/api/copilot")
def ask(m: str, q_: str = Query(alias="q"), f: str | None = None, t: str | None = None,
        surface: str = "merchant"):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return copilot.answer(m, q_, f, t, surface=surface)


@app.post("/api/copilot/feedback")
def copilot_feedback(m: str, intent: str, useful: bool, surface: str = "merchant"):
    """Lightweight 👍/👎 loop feeding AI quality monitoring."""
    _check_merchant(m)
    ai_telemetry.record_feedback(merchant_scope=m, intent=intent, useful=useful, surface=surface)
    return {"ok": True}


# --- Control Center (operator surface) ----------------------------------------
# Single-tenant hackathon build; production auth/RBAC path documented in docs/DEPLOYMENT_SPEC.md.
@app.get("/api/admin/platform")
def admin_platform(f: str | None = None, t: str | None = None):
    f, t = _dates("", f, t)
    return control.platform(f, t)


@app.get("/api/admin/performance")
def admin_performance():
    return control.performance()


@app.get("/api/admin/ai-ops")
def admin_ai_ops():
    return control.ai_ops()


@app.get("/api/admin/sources")
def admin_sources(f: str | None = None, t: str | None = None):
    f, t = _dates("", f, t)
    return control.sources(f, t)


@app.get("/api/admin/ai-eval")
@lru_cache(maxsize=1)
def admin_ai_eval():
    return run_eval()


@app.get("/api/admin/copilot")
def admin_ask(q_: str = Query(alias="q"), f: str | None = None, t: str | None = None):
    f, t = _dates("", f, t)
    return ops_copilot.answer(q_, f, t)


@app.post("/api/admin/copilot/feedback")
def admin_copilot_feedback(intent: str, useful: bool):
    ai_telemetry.record_feedback(merchant_scope="platform", intent=intent, useful=useful, surface="ops")
    return {"ok": True}


_VALID_OUTCOMES = {"verified", "paid_unverified", "no_attempt", "abandoned_inbank", "failed_bank", "reversed"}


@app.get("/api/evidence/sessions")
def evidence_sessions(m: str, outcome: str | None = None, f: str | None = None,
                      t: str | None = None, limit: int = Query(12, ge=1, le=50)):
    """Drill-through: sample source sessions behind a metric."""
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

    _STATIC_BASE = STATIC_DIR.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # Containment must be decided LEXICALLY, before any filesystem/network call.
        # Path.resolve() would open a handle first — and on Windows a "///host/share"
        # path becomes a UNC path that triggers an SMB connect (NTLM leak + threadpool
        # stall) at resolve() time, too late for is_relative_to. normpath is pure string.
        f = Path(os.path.normpath(_STATIC_BASE / path))
        if path and f.is_relative_to(_STATIC_BASE) and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
