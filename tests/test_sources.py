"""Data-source adapters: GA4 gating, safe-key projection, cross-source insight logic."""
from zarin.sources import registry
from zarin.sources.ga4 import GA4Adapter
from zarin.sources.insights import cross_source
from zarin.sources.zarinpal import ZarinPalAdapter


def test_ga4_not_configured_is_honest():
    a = GA4Adapter(property_id="", credentials_path="")
    s = a.status()
    assert s.status == "not_configured" and not s.connected and not s.configured
    assert a.metrics("2026-01-01", "2026-02-28") is None


def test_ga4_configured_without_transport_reports_error():
    a = GA4Adapter(property_id="123456", credentials_path="/creds.json", fetch_fn=None)
    s = a.status()
    assert s.configured and not s.connected and s.status == "error"


def test_ga4_with_transport_keeps_only_safe_keys():
    def fetch(pid, creds, f, t):
        return {"sessions": 1000, "users": 800, "secret_token": "leak", "raw_rows": [1, 2, 3]}
    a = GA4Adapter(property_id="123456", credentials_path="/creds.json", fetch_fn=fetch)
    assert a.status().connected
    m = a.metrics("2026-01-01", "2026-02-28")
    assert m == {"sessions": 1000, "users": 800}  # secret_token / raw_rows dropped


def test_zarinpal_is_source_of_truth():
    s = ZarinPalAdapter().status()
    assert s.is_truth and s.kind == "payment" and s.status == "ok"


def test_registry_lists_both_sources():
    assert {a.id for a in registry()} >= {"zarinpal", "ga4"}


def test_cross_source_traffic_up_payments_flat():
    before = {"ga4_sessions": 1000, "payment_verified": 500, "payment_conv": 0.5, "payment_sessions": 900}
    after = {"ga4_sessions": 1300, "payment_verified": 500, "payment_conv": 0.5, "payment_sessions": 900}
    cards = cross_source(before, after)
    assert "traffic_up_payments_flat" in {c["id"] for c in cards}
    for c in cards:                      # every cross-source card carries the no-causality caveat
        assert c["caveat_fa"] and "علّی" in c["caveat_fa"]


def test_cross_source_returns_nothing_without_traffic():
    assert cross_source({"ga4_sessions": None}, {"ga4_sessions": None}) == []
