"""Response cache for read-only marts.

The parquet marts never change while the process lives — they are rebuilt only by a
new build/deploy — so every `/api/*` GET listed below is a *pure function of its
path and query string*. That makes two caches sound, both keyed identically:

  1. the CDN / browser, via `Cache-Control: s-maxage` — costs zero compute and zero
     round-trip to the origin region;
  2. this process, via a bounded LRU of already-serialised bodies — covers a cold
     edge, a query the CDN has not seen, and any deployment fronted by no CDN at all.

Correctness note: a deploy publishes new marts *and* a new CDN cache namespace at the
same time, and a new process with an empty LRU. There is no window in which either
layer can serve a body computed from marts that no longer exist.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from starlette.responses import Response

from .config import REQUIRE_AUTH

# Deterministic, side-effect-free reads.
#
# NOT here, deliberately:
#   /api/copilot        — emits one AI-telemetry event per call, which the Control
#                         Center reports as live AI operations. Serving it from a
#                         cache would silently stop that signal.
#   /api/admin/*        — the operator gate runs in the route's dependencies, i.e.
#                         *after* this middleware. Caching here would answer before
#                         the guard. (Their heavy inner functions memoize instead.)
#   POST anything       — not a read.
CACHEABLE = frozenset({
    "/api/meta",
    "/api/overview",
    "/api/insights",
    "/api/funnel",
    "/api/customers",
    "/api/peers",
    "/api/changes",
    "/api/quality",
    "/api/evidence/sessions",
})

# One year at the edge: the response cannot go stale before the deployment that
# produced it is replaced, and a replacement invalidates the namespace. `max-age`
# stays short so a browser tab reloaded after a redeploy re-validates quickly.
_CDN_CACHE = "public, max-age=60, s-maxage=31536000, stale-while-revalidate=86400"
_NO_STORE = "no-store"
# When tenant scoping is enforced, a merchant response is PRIVATE. `public, s-maxage` on it
# would license a shared CDN to hold one merchant's money for a year and hand it to the next
# caller of the same URL.
_PRIVATE = "private, no-store"

MAX_ENTRIES = 512
MAX_BODY_BYTES = 2_000_000   # a body larger than this is not worth the resident memory

_lock = threading.Lock()
_store: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_hits = _misses = 0


def stats() -> dict:
    with _lock:
        return {"entries": len(_store), "hits": _hits, "misses": _misses,
                "hit_rate": round(_hits / (_hits + _misses), 4) if (_hits + _misses) else None}


def clear() -> None:  # testing hook
    global _hits, _misses
    with _lock:
        _store.clear()
        _hits = _misses = 0


def _get(key: str) -> tuple[bytes, str] | None:
    global _hits, _misses
    with _lock:
        v = _store.get(key)
        if v is None:
            _misses += 1
            return None
        _store.move_to_end(key)
        _hits += 1
        return v


def _put(key: str, body: bytes, ctype: str) -> None:
    if len(body) > MAX_BODY_BYTES:
        return
    with _lock:
        _store[key] = (body, ctype)
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)


async def middleware(request, call_next):
    path = request.url.path
    # THE hazard of caching in middleware, and the reason /api/admin/* is excluded above:
    # Starlette runs middleware ABOVE the route's dependency graph, so a cache hit answers
    # before `_merchant_scope` ever executes. With ZARIN_REQUIRE_AUTH=1 — the documented
    # production posture and the recorded fix for ZB-001/ZB-030 — that made the tenant guard
    # inert: one authenticated request warmed a URL, and every later anonymous or
    # wrong-merchant request to the same URL got a 200 with the full body. Verified by
    # pipeline/_panel/cache_auth_probe.py before this guard existed.
    #
    # The same reasoning that excluded /api/admin/* applies to every merchant route, so in
    # that mode nothing is cached and nothing is marked publicly cacheable. The demo default
    # (REQUIRE_AUTH off, single tenant, `m=` is the scope) keeps the cache, because there is
    # no principal to key it by and no tenant boundary to cross.
    if REQUIRE_AUTH:
        resp = await call_next(request)
        if path.startswith("/api/"):
            resp.headers["Cache-Control"] = _PRIVATE
        return resp
    if request.method != "GET" or path not in CACHEABLE:
        resp = await call_next(request)
        if path.startswith("/api/") and "cache-control" not in resp.headers:
            resp.headers["Cache-Control"] = _NO_STORE
        return resp

    key = f"{path}?{request.url.query}"
    hit = _get(key)
    if hit is not None:
        body, ctype = hit
        return Response(body, media_type=ctype,
                        headers={"Cache-Control": _CDN_CACHE, "X-Zarbin-Cache": "HIT"})

    resp = await call_next(request)
    # A middleware sees a streaming response even when the route returned JSONResponse,
    # so the body has to be drained here and re-emitted; there is no `.body` to read.
    body = b"".join([chunk async for chunk in resp.body_iterator])
    ctype = resp.headers.get("content-type", "application/json")
    headers = dict(resp.headers)
    headers.pop("content-length", None)     # rebuilt by the new Response
    headers["X-Zarbin-Cache"] = "MISS"
    if resp.status_code == 200:
        _put(key, body, ctype)
        headers["Cache-Control"] = _CDN_CACHE
    else:
        headers["Cache-Control"] = _NO_STORE   # never let the edge pin an error
    return Response(body, status_code=resp.status_code, headers=headers, media_type=ctype)
