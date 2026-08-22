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


def test_limit_out_of_range_is_422_not_500():
    # limit is bounded by Query(ge=1, le=50) → FastAPI 422, never a raw LIMIT -5 → 500
    assert client.get("/api/evidence/sessions", params={"m": "M1", "limit": -5}).status_code == 422
    assert client.get("/api/evidence/sessions", params={"m": "M1", "limit": 999}).status_code == 422
    ok = client.get("/api/evidence/sessions", params={"m": "M1", "limit": 50})
    assert ok.status_code == 200 and len(ok.json()["rows"]) <= 50


def test_basic_iso_is_normalized_and_bad_compare_dates_are_400_not_500():
    # basic-form date is normalized to canonical YYYY-MM-DD and served (never a raw 500)
    assert client.get("/api/overview", params={"m": "M1", "f": "20260101"}).status_code == 200
    # genuinely invalid dates → 400, including the comparison window (same trust boundary)
    assert client.get("/api/overview", params={"m": "M1", "f": "totally-bad"}).status_code == 400
    assert client.get("/api/overview", params={"m": "M1", "cf": "oops"}).status_code == 400


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
    probes = ("/../../pyproject.toml", "/..%2f..%2fpyproject.toml",
              "/../../data/marts/customers.parquet",
              "///10.255.255.1/share/x")  # UNC: must be rejected LEXICALLY, not by opening it
    for raw in probes:
        code, content = _raw_asgi_get(raw)
        assert code == 200
        assert b"[project]" not in content        # must not be pyproject.toml
        assert b"PAR1" not in content[:64]         # must not be a parquet file
        assert b"<div id=\"root\">" in content or b"<!doctype" in content.lower() \
            or content == b""  # served index.html (or empty when built html differs) — never the file


from itertools import pairwise

# --- round-1 panel: the three findings that outlived the first fix batch ----------------

def test_amount_bands_are_cut_on_values_not_row_rank():
    """ntile(5) is equal-COUNT, so with tied prices the SAME amount landed in several bands,
    each publishing its own conversion rate — 84 bands platform-wide had lo == hi, and up to
    four bands containing one price quoted four different rates. Bands are now cut on
    quantile VALUES, which keeps every session with a given amount in one band."""
    fu = client.get("/api/funnel?m=MPSP&f=2026-04-01&t=2026-04-30").json()
    bands = fu["amount_bands"]
    assert bands, "fixture should produce at least one band"
    # a single price may legitimately be its own band, but only when it is the ONLY band
    if len(bands) > 1:
        assert all(b["lo"] != b["hi"] for b in bands), bands
    # and no two bands may share a price
    for a, b in pairwise(bands):
        assert a["hi"] < b["lo"], (a, b)


def test_operator_drilldown_respects_the_selected_window():
    """The table read lifetime `merchant_stats` while every KPI beside it was windowed, so
    changing the period moved every number on the page except the rows in the table."""
    wide = client.get("/api/admin/merchants?sort=gmv&limit=100").json()
    narrow = client.get("/api/admin/merchants?sort=gmv&limit=100&f=2026-01-01&t=2026-01-31").json()
    assert narrow["period"] == {"from": "2026-01-01", "to": "2026-01-31"}
    wide_by = {r["merchant_key"]: r["sessions"] for r in wide["rows"]}
    narrow_by = {r["merchant_key"]: r["sessions"] for r in narrow["rows"]}
    shared = set(wide_by) & set(narrow_by)
    assert shared, "expected at least one merchant in both windows"
    assert any(narrow_by[k] < wide_by[k] for k in shared), (wide_by, narrow_by)
    # and the ranking itself must be able to change — with lifetime figures it could not
    assert [r["merchant_key"] for r in wide["rows"][:5]] != [r["merchant_key"] for r in narrow["rows"][:5]]


def test_changes_derives_one_split_server_side():
    """Two screens split the same window differently and disagreed about the same delta.
    /api/changes now derives the halves itself, with the same function the insight card
    uses, and reports the boundaries it chose."""
    d = client.get("/api/changes?m=M1&f=2026-01-01&t=2026-02-28").json()
    w = d["windows"]
    assert w["f1"] == "2026-01-01" and w["t2"] == "2026-02-28"
    # the two halves are equal length and do not overlap
    from datetime import date
    a = (date.fromisoformat(w["t1"]) - date.fromisoformat(w["f1"])).days
    b = (date.fromisoformat(w["t2"]) - date.fromisoformat(w["f2"])).days
    assert a == b, w
    assert date.fromisoformat(w["f2"]) > date.fromisoformat(w["t1"]), w
    # asking explicitly for the same halves must give the identical answer
    e = client.get(f"/api/changes?m=M1&f1={w['f1']}&t1={w['t1']}&f2={w['f2']}&t2={w['t2']}").json()
    assert e["delta_gmv"] == d["delta_gmv"]


def test_changes_rejects_an_unsplittable_window_and_partial_arguments():
    assert client.get("/api/changes?m=M1&f=2026-01-01&t=2026-01-10").status_code == 400
    assert client.get("/api/changes?m=M1&f1=2026-01-01").status_code == 400
