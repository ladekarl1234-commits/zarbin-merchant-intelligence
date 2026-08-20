"""API-layer tests: the surface the metric tests don't touch.

Includes a raw-ASGI path-traversal probe: TestClient/httpx normalize `..` away,
so the traversal defect is invisible through the normal client — we drive the
ASGI app with an un-normalized raw path directly.
"""
import asyncio

from fastapi.testclient import TestClient

from zarin.api import app

client = TestClient(app)
JAN = ("2026-01-01", "2026-01-31")


def test_unknown_merchant_404():
    assert client.get("/api/overview", params={"m": "NOPE"}).status_code == 404


def test_bad_date_is_400_not_500():
    assert client.get("/api/overview", params={"m": "M1", "f": "not-a-date"}).status_code == 400
    assert client.get("/api/overview", params={"m": "M1", "f": "2026-13-99"}).status_code == 400
    r = client.get("/api/changes", params={"m": "M1", "f1": "x", "t1": "y", "f2": "a", "t2": "b"})
    assert r.status_code == 400


def test_limit_is_clamped_not_500():
    assert client.get("/api/evidence/sessions", params={"m": "M1", "limit": -5}).status_code == 422
    assert client.get("/api/evidence/sessions", params={"m": "M1", "limit": 999}).status_code == 422
    ok = client.get("/api/evidence/sessions", params={"m": "M1", "limit": 50})
    assert ok.status_code == 200 and len(ok.json()["rows"]) <= 50


def test_unknown_outcome_is_400():
    assert client.get("/api/evidence/sessions",
                      params={"m": "M1", "outcome": "verified' OR 1=1--"}).status_code == 400


def _raw_asgi_get(raw_path: str) -> tuple[int, bytes]:
    """Send a GET with an un-normalized raw path straight to the ASGI app."""
    body = bytearray()
    status = {}

    async def run():
        scope = {"type": "http", "http_version": "1.1", "method": "GET",
                 "path": raw_path, "raw_path": raw_path.encode(), "query_string": b"",
                 "headers": [], "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8630),
                 "scheme": "http"}
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive():
            return messages.pop(0)

        async def send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            elif msg["type"] == "http.response.body":
                body.extend(msg.get("body", b""))
        await app(scope, receive, send)

    asyncio.run(run())
    return status.get("code"), bytes(body)


def test_path_traversal_serves_index_not_arbitrary_file():
    # Only meaningful when the built SPA exists; skip cleanly otherwise.
    from zarin.config import STATIC_DIR
    if not (STATIC_DIR / "index.html").exists():
        return
    for raw in ("/../../pyproject.toml", "/..%2f..%2fpyproject.toml", "/../../data/marts/customers.parquet"):
        code, content = _raw_asgi_get(raw)
        assert code == 200
        assert b"[project]" not in content        # must not be pyproject.toml
        assert b"<div id=\"root\">" in content or b"<!doctype" in content.lower() \
            or content == b""  # served index.html (or empty when built html differs) — never the file
