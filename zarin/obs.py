"""Request observability — per-endpoint latency, error rate, throughput.

In-memory only (request telemetry is high-volume); the ring is what Product
Performance reads. Latency is measured server-side around the route handler.
"""
from __future__ import annotations

import time
from collections import defaultdict

from .config import TELEMETRY_DIR
from .fa import fa_num, fa_pct
from .store import EventLog

_reqs = EventLog(TELEMETRY_DIR / "requests.jsonl", maxlen=8000, durable=False)


def record(method: str, path: str, status: int, latency_ms: float) -> None:
    _reqs.add({"method": method, "path": path, "status": int(status),
               "latency_ms": round(latency_ms, 2), "t": time.time()})


def _trackable(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith("/api/docs") and path != "/api/openapi.json"


def _label(request) -> str:
    """The ROUTE, not the URL.

    `record` keyed on the raw path, and the ring holds 8,000 events. Any caller could
    therefore GET /api/aaa1 … /api/aaa9000 — each a 404, each a distinct key — and both evict
    every real measurement and inflate /api/admin/performance's endpoint list 200x. Bucketing
    unmatched paths under one label makes the ring bounded by the number of routes, which is
    a constant, instead of by the number of URLs a stranger can invent.
    """
    route = request.scope.get("route")
    tmpl = getattr(route, "path", None)
    if not tmpl or "{path" in tmpl:
        return "<unmatched>"
    return tmpl


async def middleware(request, call_next):
    t0 = time.perf_counter()
    path = request.url.path
    try:
        resp = await call_next(request)
    except Exception:
        # An unhandled exception never reaches call_next's return, so without this the
        # request vanishes from telemetry and error_rate stays pinned at 0 (ZB-021).
        if _trackable(path):
            record(request.method, _label(request), 500, (time.perf_counter() - t0) * 1000)
        raise
    dt_ms = (time.perf_counter() - t0) * 1000
    if _trackable(path):
        record(request.method, _label(request), resp.status_code, dt_ms)
    # Server-Timing carries the server's OWN cost to the client, so a latency number can be
    # attributed instead of guessed: measuring a deployment from a laptop otherwise mixes
    # ~400 ms of client RTT into every figure and makes the app look ten times slower than
    # it is. Standard header, read natively by Chrome DevTools.
    resp.headers["Server-Timing"] = f"app;dur={dt_ms:.1f}"
    return resp


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, round(q * (len(s) - 1)))], 1)


def summary() -> dict:
    ev = _reqs.recent()
    total = len(ev)
    if not total:
        return {"total": 0, "has_data": False,
                "note_fa": "هنوز درخواستی به API ثبت نشده است. با استفاده از داشبورد، این بخش زنده پر می‌شود."}

    lat_all = [e["latency_ms"] for e in ev]
    errors = [e for e in ev if e["status"] >= 500]
    client_err = [e for e in ev if 400 <= e["status"] < 500]
    span = max(1e-6, ev[-1]["t"] - ev[0]["t"])

    by_ep: dict[str, list[dict]] = defaultdict(list)
    for e in ev:
        by_ep[e["path"]].append(e)
    endpoints = []
    for path, es in by_ep.items():
        lats = [x["latency_ms"] for x in es]
        errs = sum(1 for x in es if x["status"] >= 500)
        endpoints.append({
            "path": path, "count": len(es),
            "error_rate": round(errs / len(es), 4),
            # 4xx was aggregated platform-wide but never per endpoint, so `attention` could
            # not see a route answering every single call with a 400 — a broken client or a
            # renamed parameter looked exactly like a healthy endpoint.
            "client_error_rate": round(sum(1 for x in es if 400 <= x["status"] < 500) / len(es), 4),
            "p50": _pct(lats, 0.5), "p95": _pct(lats, 0.95), "p99": _pct(lats, 0.99),
        })
    endpoints.sort(key=lambda x: (x["p95"] or 0), reverse=True)

    # decision-oriented attention: slow or erroring endpoints, only when real
    attention = []
    for ep in endpoints:
        if ep["error_rate"] > 0:
            attention.append({"severity": "high", "path": ep["path"],
                              "fa": f"مسیر {ep['path']} نرخ خطای سرور {fa_pct(ep['error_rate'])} دارد"})
        elif ep["client_error_rate"] > 0.5 and ep["count"] >= 10:
            attention.append({"severity": "medium", "path": ep["path"],
                              "fa": (f"بیش از نیمی از درخواست‌های {ep['path']} با خطای کلاینت رد می‌شوند "
                                     f"({fa_pct(ep['client_error_rate'])}) — احتمالاً قرارداد ورودی شکسته است")})
        elif (ep["p95"] or 0) > 1500:
            attention.append({"severity": "medium", "path": ep["path"],
                              "fa": f"مسیر {ep['path']} کند است (p95 برابر {fa_num(ep['p95'])} میلی‌ثانیه)"})

    return {
        "total": total, "has_data": True,
        "error_rate": round(len(errors) / total, 4),
        "client_error_rate": round(len(client_err) / total, 4),
        "throughput_rps": round(total / span, 2),
        "latency_ms": {"p50": _pct(lat_all, 0.5), "p95": _pct(lat_all, 0.95), "p99": _pct(lat_all, 0.99)},
        "endpoints": endpoints,
        "attention": attention,
        # Said out loud, because the panel looks like site-wide traffic and is not: this ring
        # is per process and non-durable, and a CDN hit never reaches the origin at all. On
        # the deployed build most read traffic is served from the edge, so these counts are
        # ORIGIN requests, which is a strict subset of what users did.
        "scope_fa": ("این اعداد فقط درخواست‌هایی را می‌شمارند که به همین نمونهٔ سرور رسیده‌اند؛ "
                     "پاسخ‌های ارائه‌شده از CDN و نمونه‌های دیگر در آن نیستند."),
        "scope": "origin-requests-this-instance",
    }


def reset() -> None:  # testing hook
    _reqs.clear()
