"""FastAPI app: /api/* JSON endpoints + static frontend."""
from __future__ import annotations

import hmac
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import analytics, auth, cache, control, copilot, insights, obs, ops_copilot, peers
from .ai import telemetry as ai_telemetry
from .ai.eval import run_eval
from .config import (
    ADMIN_TOKEN,
    CURRENCY_NOTE,
    CUSTOMER_SCOPE_CAVEAT,
    FEE_CAVEAT,
    HOST,
    MAX_QUESTION_LEN,
    REQUIRE_AUTH,
    STATIC_DIR,
)
from .copilot import _equal_halves
from .db import q, q1
from .fa import fa_num

app = FastAPI(title="Zarbin — زرین‌بین", docs_url="/api/docs", openapi_url="/api/openapi.json")
# Registration order matters: Starlette runs the LAST-registered middleware outermost, so
# obs must be registered after cache to keep seeing every request — including the ones the
# cache answers, which are exactly the requests Product Performance should show as fast.
app.middleware("http")(cache.middleware)  # deterministic-read cache + CDN cache headers
app.middleware("http")(obs.middleware)    # request telemetry → Control Center Product Performance


# --- Response contracts (ZB-009) -----------------------------------------------
# Loose on purpose: nested payloads (kpis, evidence, cards, ...) come from
# analytics.py/insights.py/peers.py, which are evolving concurrently, so fields
# inside them are typed Any rather than pinned — the point is a real OpenAPI
# schema and byte-for-byte compatibility with today's frontend, not a rewrite.
class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class OverviewResponse(_Loose):
    period: dict[str, Any]
    compare: dict[str, Any] | None = None
    kpis: dict[str, Any]
    previous: dict[str, Any] | None = None
    daily: list[dict[str, Any]]
    evidence: dict[str, Any]


class InsightsResponse(_Loose):
    cards: list[dict[str, Any]]


class FunnelResponse(_Loose):
    period: dict[str, Any]
    stages: list[dict[str, Any]]
    outcomes: dict[str, Any]
    rates: dict[str, Any]
    recovery: dict[str, Any]
    hours: list[dict[str, Any]]
    amount_bands: list[dict[str, Any]]
    psp: list[dict[str, Any]]
    fail_codes: list[dict[str, Any]]
    evidence: dict[str, Any]


class PeersResponse(_Loose):
    group: dict[str, Any]
    rows: list[dict[str, Any]]
    evidence: dict[str, Any]


class ChangesResponse(_Loose):
    before: dict[str, Any]
    after: dict[str, Any]
    delta_gmv: float
    decomposable: bool
    contrib: dict[str, Any]
    conv_drivers: dict[str, Any]
    evidence: dict[str, Any]


class QualityResponse(_Loose):
    outcomes: list[dict[str, Any]]
    concentration: dict[str, Any]
    anomalies: dict[str, Any]
    rules_fa: list[str]


def _range() -> tuple[str, str]:
    r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
    return str(r["f"]), str(r["t"])


def _check_merchant(m: str) -> None:
    if not q1("SELECT 1 AS x FROM merchant_stats WHERE merchant_key=$m", {"m": m}):
        raise HTTPException(404, f"merchant {m} not found")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _merchant_scope(m: str, authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency binding the merchant every /api/* merchant route trusts (ZB-001/ZB-030).

    REQUIRE_AUTH off (demo default): the `m=` query param is used exactly as before this
    module existed. REQUIRE_AUTH on: `m` MUST come from a verified merchant-scope session
    token; a query `m` that doesn't match the token's merchant_key is rejected with 403.
    """
    if not REQUIRE_AUTH:
        return m
    claims = auth.verify(_bearer_token(authorization))
    if not claims or claims.get("scope") != "merchant" or not claims.get("merchant_key"):
        raise HTTPException(401, "valid merchant session required")
    if claims["merchant_key"] != m:
        raise HTTPException(403, "session merchant does not match m")
    return m


def _ops_session(authorization: str | None) -> bool:
    claims = auth.verify(_bearer_token(authorization))
    return bool(claims and claims.get("scope") == "ops")


def _admin_guard(x_admin_token: str | None = Header(default=None),
                  authorization: str | None = Header(default=None)) -> None:
    """Operator gate for /api/admin/*.

    - ZARIN_ADMIN_TOKEN set and header matches -> always passes (back-compat).
      Wrong header -> 401, unless ZARIN_REQUIRE_AUTH=1 and an ops-scope session is present.
    - No ZARIN_ADMIN_TOKEN, but ZARIN_REQUIRE_AUTH=1 *or* a non-loopback HOST -> a signed,
      expiring ops-scope session token is required (ZB-001/ZB-019). A public deploy used to
      get a flat 503 here, which took the whole operator surface off the air instead of
      gating it; the gate is the session, and the demo's ops login mints one.
    - ZARIN_ADMIN_TOKEN unset and HOST loopback, REQUIRE_AUTH off -> open (demo default).
    """
    if ADMIN_TOKEN:
        if hmac.compare_digest(x_admin_token or "", ADMIN_TOKEN):
            return
        if REQUIRE_AUTH and _ops_session(authorization):
            return
        raise HTTPException(401, "operator token required for the Control Center API")
    if REQUIRE_AUTH or not _is_loopback(HOST):
        if _ops_session(authorization):
            return
        raise HTTPException(403, "ops session required")


def _check_question(q_: str) -> str:
    if len(q_) > MAX_QUESTION_LEN:
        raise HTTPException(400, f"question too long (max {MAX_QUESTION_LEN} chars)")
    return q_


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
        FROM merchant_stats ORDER BY gmv DESC NULLS LAST, merchant_key""")
    # demo presets are selected programmatically, not hardcoded conclusions. Each preset
    # takes the top merchant that isn't already used by an earlier preset, so a collision
    # (e.g. the top-GMV merchant is also the paid-unverified leader) never drops a preset.
    ranks = q("""
        WITH s AS (SELECT merchant_key,
            gmv, paid_unverified_amount AS pua, repeat_txns,
            no_attempt / nullif(sessions,0) AS na_rate,
            recovered / nullif(sessions,0) AS rec_rate
          FROM merchant_stats WHERE sessions >= 5000)
        -- merchant_key breaks ties so a preset always names the same merchant between runs.
        -- repeat_txns alone has 26 tied groups, so «بیشترین مشتری تکراری» was genuinely unstable.
        SELECT merchant_key,
               row_number() OVER (ORDER BY gmv DESC, merchant_key) AS r_gmv,
               row_number() OVER (ORDER BY pua DESC, merchant_key) AS r_pua,
               row_number() OVER (ORDER BY na_rate DESC, merchant_key) AS r_na,
               row_number() OVER (ORDER BY rec_rate DESC, merchant_key) AS r_rec,
               row_number() OVER (ORDER BY repeat_txns DESC, merchant_key) AS r_rep
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


@app.post("/api/auth/session")
def auth_session(scope: str, merchant_key: str | None = None):
    """Issue a session token (ZB-001/ZB-030). Unused unless ZARIN_REQUIRE_AUTH=1 —
    the demo default keeps trusting the `m=` query param on every merchant route."""
    if scope not in ("merchant", "ops"):
        raise HTTPException(400, f"invalid scope: {scope!r} (expected 'merchant' or 'ops')")
    if scope == "merchant":
        if merchant_key:
            _check_merchant(merchant_key)
        elif REQUIRE_AUTH:
            # With auth enforced, an unbound merchant token would defeat tenant scoping.
            raise HTTPException(400, "merchant_key required for scope='merchant' when ZARIN_REQUIRE_AUTH=1")
        # Demo default: the merchant is chosen from the picker AFTER login, so a token issued at
        # login carries no merchant claim. It is inert — merchant routes still read `m=` while
        # REQUIRE_AUTH is off, and reject an unbound token once it is on.
    else:
        merchant_key = None
    return {"token": auth.issue(scope, merchant_key), "scope": scope, "merchant_key": merchant_key}


@app.get("/api/overview", response_model=OverviewResponse)
def overview(m: str = Depends(_merchant_scope), f: str | None = None, t: str | None = None,
             cf: str | None = None, ct: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    cf = _valid_date(cf, "cf") if cf else None   # comparison window is the same trust boundary
    ct = _valid_date(ct, "ct") if ct else None
    return analytics.overview(m, f, t, cf, ct)


@app.get("/api/insights", response_model=InsightsResponse)
def get_insights(m: str = Depends(_merchant_scope), f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return {"cards": insights.generate(m, f, t)}


@app.get("/api/funnel", response_model=FunnelResponse)
def funnel(m: str = Depends(_merchant_scope), f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return analytics.funnel(m, f, t)


@app.get("/api/customers")
def customers(m: str = Depends(_merchant_scope), f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return analytics.customers(m, f, t)


@app.get("/api/peers", response_model=PeersResponse)
def get_peers(m: str = Depends(_merchant_scope), f: str | None = None, t: str | None = None):
    _check_merchant(m)
    f, t = _dates(m, f, t)
    return peers.benchmarks(m, f, t)


@app.get("/api/changes", response_model=ChangesResponse)
def changes(m: str = Depends(_merchant_scope),
            f1: str | None = None, t1: str | None = None,
            f2: str | None = None, t2: str | None = None,
            f: str | None = None, t: str | None = None):
    """Decompose a GMV move between two windows.

    Two ways to ask. Explicit (`f1,t1,f2,t2`) is unchanged. Derived (`f,t`) splits the window
    into two equal halves SERVER-SIDE with `copilot._equal_halves` — the same function the
    "GMV change" insight card uses.

    That second form exists because the Changes page used to compute the split itself in
    TypeScript, and the two implementations disagreed: the card dropped the middle day of an
    odd span (ZB-018) and the page did not, so the same merchant's ΔGMV differed by 9.06
    billion IRR depending on which screen you read it from. One split, derived once, and the
    response says which boundaries were used.
    """
    _check_merchant(m)
    if not any((f1, t1, f2, t2)):
        lo, hi = _dates(m, f, t)
        halves = _equal_halves(lo, hi)
        if not halves:
            raise HTTPException(400, "window too short to split into two comparable halves "
                                     "(28 days minimum); pass f1,t1,f2,t2 explicitly")
        a_end, b_start, _half = halves
        f1, t1, f2, t2 = lo, a_end, b_start, hi
    elif not all((f1, t1, f2, t2)):
        raise HTTPException(400, "give all four of f1,t1,f2,t2 — or none, and f/t instead")
    # reassign the NORMALIZED dates (not just validate) so basic-form ISO like 20260101
    # reaches DuckDB as canonical YYYY-MM-DD instead of raising a 500 — mirrors _dates().
    f1, t1 = _valid_date(f1, "f1"), _valid_date(t1, "t1")
    f2, t2 = _valid_date(f2, "f2"), _valid_date(t2, "t2")
    out = analytics.changes(m, f1, t1, f2, t2)
    out["windows"] = {"f1": f1, "t1": t1, "f2": f2, "t2": t2}
    return out


@app.get("/api/copilot")
def ask(q_: str = Query(alias="q"), m: str = Depends(_merchant_scope), f: str | None = None,
        t: str | None = None, surface: str = "merchant"):
    """The answer. Deterministic, always — the LLM is never on this path.

    Measured on the free-model policy this product is committed to: the best model that
    OpenRouter's free tier actually serves adds 3.2s on average (5.1s p95) and its output
    is discarded by the grounding guard about one time in five. Putting that in front of an
    answer the engine already has in ~40ms would make every question slower and one in five
    of them no better. `/api/copilot/polish` offers the same answer, rephrased, to a client
    that has already rendered this one.
    """
    _check_merchant(m)
    q_ = _check_question(q_)
    f, t = _dates(m, f, t)
    return copilot.answer(m, q_, f, t, surface=surface, use_llm=False)


@app.get("/api/copilot/polish")
def polish(q_: str = Query(alias="q"), m: str = Depends(_merchant_scope), f: str | None = None,
           t: str | None = None, surface: str = "merchant"):
    """Optional second pass: the SAME deterministic answer, rephrased by the LLM.

    Progressive enhancement. The client renders /api/copilot immediately and calls this
    afterwards; if it returns `source == "llm"` the wording is swapped in, and if it is slow,
    rate-limited, ungrounded or the key is absent, the client simply keeps what it already
    showed. Every response is still grounding-guarded, so a swap can only ever change wording.
    """
    _check_merchant(m)
    q_ = _check_question(q_)
    f, t = _dates(m, f, t)
    return copilot.answer(m, q_, f, t, surface=surface, use_llm=True)


@app.post("/api/copilot/feedback")
def copilot_feedback(intent: str, useful: bool, m: str = Depends(_merchant_scope), surface: str = "merchant"):
    """Lightweight 👍/👎 loop feeding AI quality monitoring."""
    _check_merchant(m)
    ai_telemetry.record_feedback(merchant_scope=m, intent=intent, useful=useful, surface=surface)
    return {"ok": True}


# --- Control Center (operator surface) ----------------------------------------
# Single-tenant hackathon build; _admin_guard enforces ZARIN_ADMIN_TOKEN when set (open on
# loopback by default). Production auth/RBAC path documented in docs/DEPLOYMENT_SPEC.md.
_ADMIN = [Depends(_admin_guard)]


@app.get("/api/admin/platform", dependencies=_ADMIN)
def admin_platform(f: str | None = None, t: str | None = None):
    f, t = _dates("", f, t)
    return control.platform(f, t)


_MERCHANT_SORTS = {"unverified", "no_attempt", "gmv", "recovered"}


@app.get("/api/admin/merchants", dependencies=_ADMIN)
def admin_merchants(sort: str = "unverified", limit: int = Query(20, ge=1, le=100),
                    f: str | None = None, t: str | None = None):
    """Merchant drilldown behind the Control Center's recommended actions (ZB-026).

    Takes the window, like every other operator route. Without it the table showed lifetime
    figures under a header that named the selected period.
    """
    if sort not in _MERCHANT_SORTS:
        raise HTTPException(400, f"unknown sort: {sort!r} (expected one of {sorted(_MERCHANT_SORTS)})")
    f, t = _dates("", f, t)
    return control.merchants(sort, limit, f, t)


@app.get("/api/admin/performance", dependencies=_ADMIN)
def admin_performance():
    return control.performance()


@app.get("/api/admin/ai-ops", dependencies=_ADMIN)
def admin_ai_ops():
    return control.ai_ops()


@app.get("/api/admin/sources", dependencies=_ADMIN)
def admin_sources(f: str | None = None, t: str | None = None):
    f, t = _dates("", f, t)
    return control.sources(f, t)


@app.get("/api/admin/ai-eval", dependencies=_ADMIN)
def admin_ai_eval():
    return _cached_eval()


@lru_cache(maxsize=1)
def _cached_eval():
    return run_eval()


@app.get("/api/admin/copilot", dependencies=_ADMIN)
def admin_ask(q_: str = Query(alias="q"), f: str | None = None, t: str | None = None):
    """Operator copilot. Deterministic for the same reason as the merchant one."""
    q_ = _check_question(q_)
    f, t = _dates("", f, t)
    return ops_copilot.answer(q_, f, t, use_llm=False)


@app.get("/api/admin/copilot/polish", dependencies=_ADMIN)
def admin_polish(q_: str = Query(alias="q"), f: str | None = None, t: str | None = None):
    q_ = _check_question(q_)
    f, t = _dates("", f, t)
    return ops_copilot.answer(q_, f, t, use_llm=True)


@app.post("/api/admin/copilot/feedback", dependencies=_ADMIN)
def admin_copilot_feedback(intent: str, useful: bool):
    ai_telemetry.record_feedback(merchant_scope="platform", intent=intent, useful=useful, surface="ops")
    return {"ok": True}


_VALID_OUTCOMES = {"verified", "paid_unverified", "no_attempt", "abandoned_inbank", "failed_bank", "reversed"}


@app.get("/api/evidence/sessions")
def evidence_sessions(m: str = Depends(_merchant_scope), outcome: str | None = None, f: str | None = None,
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
        -- session_key breaks amount ties: 17k sessions share an amount, and an evidence
        -- drawer that returns different rows for the same query is not auditable.
        ORDER BY amount DESC, session_key LIMIT {int(limit)}""",
        {"m": m, "f": f, "t": t, **({"o": outcome} if outcome else {})})
    total = q1(f"SELECT count(*) AS n FROM sessions WHERE merchant_key=$m AND d BETWEEN $f AND $t {cond}",
               {"m": m, "f": f, "t": t, **({"o": outcome} if outcome else {})})
    return {"rows": rows, "total": total["n"],
            "note_fa": "نمونه جلسه‌های منبع (به ترتیب مبلغ). session_key همان شناسه ردیف‌های دیتاست اصلی است."}


def _live_quality_anomalies() -> dict:
    """Fallback when the pipeline sidecar is missing (old mart dir) — ZB-025."""
    dq = q1("""SELECT
        (SELECT count(*) FROM sessions WHERE session_status='Verified' AND outcome='verified'
           AND session_key IN (SELECT session_key FROM attempts GROUP BY 1 HAVING sum(ok::int)=0)) AS verified_wo_ok_try,
        (SELECT count(*) FROM sessions WHERE session_status='Verified' AND outcome='verified'
           AND session_key IN (SELECT session_key FROM attempts GROUP BY 1
                                HAVING sum((try_status='Verified')::int)=0)) AS verified_wo_verified_try,
        (SELECT count(*) FROM sessions WHERE outcome='reversed') AS reversed_sessions""")
    return dq


@app.get("/api/quality", response_model=QualityResponse)
@lru_cache(maxsize=1)
def quality():
    outcomes = q("SELECT outcome, count(*) AS n, sum(amount) AS amount FROM sessions "
                 "GROUP BY 1 ORDER BY n DESC, outcome")
    conc = q1("""WITH g AS (SELECT merchant_key, sum(gmv) AS gmv FROM merchant_daily GROUP BY 1),
                 r AS (SELECT gmv, row_number() OVER (ORDER BY gmv DESC, merchant_key) AS rk FROM g)
                 SELECT sum(gmv) FILTER (WHERE rk<=5)/sum(gmv) AS top5, count(*) AS n FROM r""")
    dq = control._dq_sidecar()
    if dq is not None:
        anomalies = {"verified_wo_ok_try": dq["verified_wo_ok_try"],
                     "verified_wo_verified_try": dq["verified_wo_verified_try"],
                     "reversed_sessions": dq["reversed_sessions"]}
    else:
        anomalies = _live_quality_anomalies()
    # ZB-010: both counts come from the query above (they differ only in whether a Paid
    # attempt counts as "ok"), not a literal that goes stale the moment the dataset changes.
    return {
        "outcomes": outcomes, "concentration": conc, "anomalies": anomalies,
        "rules_fa": [
            "هر ردیف دیتاست یک «تلاش پرداخت» است؛ همه متریک‌ها روی سطح «جلسه» محاسبه می‌شوند تا تلاش‌های تکراری چیزی را چند بار نشمارند.",
            "NoAttempt (try_seq=0) یعنی پرداخت‌کننده هرگز به درگاه نرسید؛ این حالت از خطای بانکی جداست.",
            "موفقیت = جلسه Verified. جلسه‌های Paid تسویه شده‌اند اما تایید پذیرنده ندارند و جدا گزارش می‌شوند.",
            "شناسه کارت فقط در تلاش‌های به سرانجام رسیده ثبت شده و بین پذیرنده‌ها مشترک نیست؛ تحلیل مشتری فقط پرداخت‌کنندگان موفق همان پذیرنده است.",
            FEE_CAVEAT,
            "اختلاف چندثانیه‌ای ساعت بین created_at و try_created_at (جیتر ساعت سرور) دست‌نخورده باقی مانده است.",
            (f"{fa_num(anomalies['verified_wo_verified_try'])} جلسه Verified بدون تلاش دقیقاً Verified وجود دارد؛ "
             f"از این میان {fa_num(anomalies['verified_wo_ok_try'])} جلسه حتی تلاش تسویه‌شده/OK هم ندارند. "
             f"همچنین {fa_num(anomalies['reversed_sessions'])} جلسه Reversed در داده هست. اصلاح نشده‌اند و مستند شده‌اند."),
            CURRENCY_NOTE,
        ],
    }


# Vite fingerprints every asset filename, so the content behind a given /assets/* URL can
# never change — a year at the edge with `immutable` is exactly right, and it is what keeps
# a repeat page load off the origin entirely.
_ASSET_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    _STATIC_BASE = STATIC_DIR.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # An unknown /api/* path must NOT fall through to the SPA. It used to: the catch-all
        # answered `/api/typo` with index.html and HTTP 200, so a client bug (or a probe)
        # got "success" and a body of HTML where JSON was contracted.
        if path.startswith("api/"):
            raise HTTPException(404, f"no such endpoint: /{path}")
        # Containment must be decided LEXICALLY, before any filesystem/network call.
        # Path.resolve() would open a handle first — and on Windows a "///host/share"
        # path becomes a UNC path that triggers an SMB connect (NTLM leak + threadpool
        # stall) at resolve() time, too late for is_relative_to. normpath is pure string.
        f = Path(os.path.normpath(_STATIC_BASE / path))
        if path and f.is_relative_to(_STATIC_BASE) and f.is_file():
            return FileResponse(f, headers=_ASSET_CACHE if path.startswith("assets/") else None)
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "public, max-age=0, must-revalidate"})
