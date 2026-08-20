"""Google Analytics 4 adapter — web/product-analytics signals (NOT financial truth).

Config-gated on GA4_PROPERTY_ID + GOOGLE_APPLICATION_CREDENTIALS. The transport
(the actual GA4 Data API `runReport` call) is injected via `fetch_fn` so:
  - no Google SDK is coupled into the semantic layer;
  - it is unit-testable with a fake transport;
  - with no credentials the product runs unaffected and reports an honest status.

GA4 metrics are aggregate web signals and are never merged row-level with payment
truth — only compared over compatible time windows. See docs/PLATFORM_BOOK (GA4).
"""
from __future__ import annotations

from collections.abc import Callable

from ..config import GA4_PROPERTY_ID, GOOGLE_APPLICATION_CREDENTIALS
from .base import SourceStatus

# A transport takes (property_id, credentials_path, date_from, date_to) and returns
# a dict of safe aggregate GA4 metrics, or raises on failure.
Ga4Fetch = Callable[[str, str, str, str], dict]


class GA4Adapter:
    id = "ga4"
    name_fa = "گوگل آنالیتیکس ۴"

    def __init__(self, property_id: str = GA4_PROPERTY_ID,
                 credentials_path: str = GOOGLE_APPLICATION_CREDENTIALS,
                 fetch_fn: Ga4Fetch | None = None):
        self.property_id = property_id
        self.credentials_path = credentials_path
        self._fetch = fetch_fn

    @property
    def configured(self) -> bool:
        return bool(self.property_id and self.credentials_path)

    def status(self) -> SourceStatus:
        if not self.configured:
            return SourceStatus(
                id=self.id, name_fa=self.name_fa, kind="web_analytics",
                configured=False, connected=False, status="not_configured",
                note_fa="برای اتصال، متغیرهای GA4_PROPERTY_ID و GOOGLE_APPLICATION_CREDENTIALS را تنظیم کنید. "
                        "این منبع سیگنال ترافیک/رفتار وب است، نه حقیقت مالی.",
            )
        if self._fetch is None:
            return SourceStatus(
                id=self.id, name_fa=self.name_fa, kind="web_analytics",
                configured=True, connected=False, status="error",
                note_fa="اعتبارنامه تنظیم شده اما ترانسپورت GA4 Data API در این نسخه وصل نشده است (docs/PLATFORM_BOOK).",
                error="no GA4 transport wired",
            )
        return SourceStatus(
            id=self.id, name_fa=self.name_fa, kind="web_analytics",
            configured=True, connected=True, status="ok",
            note_fa="سیگنال‌های ترافیک و تعامل وب. با حقیقت پرداخت به‌صورت سطر‌به‌سطر ادغام نمی‌شود.",
        )

    def metrics(self, f: str, t: str) -> dict | None:
        if not self.configured or self._fetch is None:
            return None
        try:
            data = self._fetch(self.property_id, self.credentials_path, f, t)
        except Exception as e:  # noqa: BLE001 — transport failures must not break the Control Center
            return {"error": str(e)}
        # keep only safe aggregate keys
        allow = ("sessions", "users", "new_users", "engaged_sessions", "conversions",
                 "purchase_events", "add_to_cart", "begin_checkout", "engagement_rate")
        return {k: data[k] for k in allow if k in data}
