"""The response cache must never answer a merchant route before the tenant guard.

Starlette runs HTTP middleware ABOVE the route's dependency graph, so a cache hit returns
before `_merchant_scope` executes. With ZARIN_REQUIRE_AUTH=1 — the documented production
posture, and the recorded fix for ZB-001/ZB-030 — that made the tenant guard inert: one
authenticated request warmed a URL and every later anonymous or wrong-merchant request to the
same URL received a 200 with the full body, marked `Cache-Control: public, s-maxage=31536000`
for a shared CDN to hold for a year.

`zarin/cache.py` already reasoned about exactly this hazard for `/api/admin/*`. It did not
apply the same reasoning to `_merchant_scope`, which is also a route dependency.

These tests run in a SUBPROCESS because REQUIRE_AUTH is read at import time.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

_PROBE = textwrap.dedent('''
    import os, sys, json
    os.environ["ZARIN_REQUIRE_AUTH"] = "1"
    os.environ["ZARIN_MARTS_DIR"] = sys.argv[1]
    os.environ["ZARIN_TELEMETRY_DIR"] = sys.argv[2]
    from fastapi.testclient import TestClient
    from zarin.api import app
    from zarin import auth
    c = TestClient(app)
    m1 = auth.issue("merchant", "M1")
    m2 = auth.issue("merchant", "M2")
    warm = c.get("/api/overview?m=M1", headers={"Authorization": f"Bearer {m1}"})
    anon = c.get("/api/overview?m=M1")
    cross = c.get("/api/overview?m=M1", headers={"Authorization": f"Bearer {m2}"})
    print(json.dumps({
        "warm_status": warm.status_code,
        "warm_cache_control": warm.headers.get("cache-control"),
        "anon_status": anon.status_code,
        "anon_bytes": len(anon.content),
        "cross_status": cross.status_code,
    }))
''')


def _probe() -> dict:
    import json
    import os
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, os.environ["ZARIN_MARTS_DIR"], os.environ["ZARIN_TELEMETRY_DIR"]],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_warm_cache_does_not_serve_a_tenant_route_to_an_anonymous_caller():
    r = _probe()
    assert r["warm_status"] == 200, r
    assert r["anon_status"] == 401, f"cache answered before the auth dependency: {r}"


def test_warm_cache_does_not_serve_one_merchant_to_another():
    r = _probe()
    assert r["cross_status"] == 403, f"cross-tenant leak through the cache: {r}"


def test_a_tenant_response_is_never_marked_publicly_cacheable():
    """Independent of the process LRU: `public, s-maxage=31536000` on a per-tenant body
    licenses any shared CDN in front of this service to hold one merchant's money for a year
    and hand it to the next caller of the same URL."""
    r = _probe()
    cc = (r["warm_cache_control"] or "").lower()
    assert "public" not in cc, cc
    assert "private" in cc or "no-store" in cc, cc
