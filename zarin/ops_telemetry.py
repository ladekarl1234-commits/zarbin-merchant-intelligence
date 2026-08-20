"""In-process operational telemetry for the single-node evaluator deployment.

This is intentionally lightweight. Production deployments should export the same
measurements to OpenTelemetry/a durable metrics backend rather than relying on process memory.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from threading import Lock
from typing import Any

from fastapi import Request

_EVENTS: deque[dict[str, Any]] = deque(maxlen=2000)
_LOCK = Lock()


def _route_label(path: str) -> str:
    """Bound cardinality by collapsing evidence and merchant-specific details."""
    if path.startswith("/api/evidence/"):
        return "/api/evidence/*"
    if path.startswith("/api/admin/"):
        return "/api/admin/*"
    return path


async def observe_http(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        event = {
            "route": _route_label(request.url.path),
            "method": request.method,
            "status": status,
            "latency_ms": latency_ms,
            "success": status < 500,
        }
        with _LOCK:
            _EVENTS.append(event)


def stats() -> dict[str, Any]:
    with _LOCK:
        events = list(_EVENTS)
    if not events:
        return {
            "requests": 0,
            "success_rate": None,
            "error_rate": None,
            "avg_latency_ms": None,
            "p95_latency_ms": None,
            "routes": {},
        }
    latencies = sorted(float(e["latency_ms"]) for e in events)
    n = len(events)
    p95 = latencies[min(n - 1, int(0.95 * (n - 1)))]
    routes = Counter(str(e["route"]) for e in events)
    successes = sum(bool(e["success"]) for e in events)
    return {
        "requests": n,
        "success_rate": successes / n,
        "error_rate": 1 - successes / n,
        "avg_latency_ms": sum(latencies) / n,
        "p95_latency_ms": p95,
        "routes": dict(routes.most_common(12)),
    }
