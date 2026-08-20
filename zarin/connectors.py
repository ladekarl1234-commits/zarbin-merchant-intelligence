"""External data-source adapters.

The challenge CSV remains the default source. External sources are optional and isolated
behind adapters so the analytical core does not depend on a vendor SDK.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import ROOT

EXTERNAL_DIR = Path(os.environ.get("ZARIN_EXTERNAL_DIR", ROOT / "data" / "external"))
GA4_SNAPSHOT = EXTERNAL_DIR / "ga4_latest.json"


@dataclass(frozen=True)
class SourceStatus:
    id: str
    label: str
    configured: bool
    state: str
    detail: str
    last_sync: str | None = None


def ga4_status() -> SourceStatus:
    property_id = os.environ.get("GA4_PROPERTY_ID", "").strip()
    credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    configured = bool(property_id and credentials)
    last_sync = None
    if GA4_SNAPSHOT.exists():
        try:
            payload = json.loads(GA4_SNAPSHOT.read_text(encoding="utf-8"))
            last_sync = payload.get("synced_at")
        except (OSError, json.JSONDecodeError):
            pass
    if not configured:
        return SourceStatus(
            id="ga4",
            label="Google Analytics 4",
            configured=False,
            state="not_configured",
            detail="برای اتصال، GA4_PROPERTY_ID و GOOGLE_APPLICATION_CREDENTIALS را تنظیم کنید.",
            last_sync=last_sync,
        )
    return SourceStatus(
        id="ga4",
        label="Google Analytics 4",
        configured=True,
        state="ready" if last_sync else "configured",
        detail="اتصال آماده است؛ همگام‌سازی به‌صورت دستی یا زمان‌بندی‌شده قابل اجراست.",
        last_sync=last_sync,
    )


def source_statuses() -> list[dict[str, Any]]:
    ga = ga4_status()
    return [
        {
            "id": "challenge",
            "label": "دیتاست تراکنش زرین‌پال",
            "configured": True,
            "state": "ready",
            "detail": "منبع اصلی متریک‌های پرداخت و منبع حقیقت تحلیلی فعلی.",
            "last_sync": None,
        },
        ga.__dict__,
        {
            "id": "openrouter",
            "label": "OpenRouter AI",
            "configured": bool(os.environ.get("OPENROUTER_API_KEY")),
            "state": "ready" if os.environ.get("OPENROUTER_API_KEY") else "fallback",
            "detail": "مدل پیش‌فرض openrouter/free است؛ بدون کلید، دستیار قطعی داخلی فعال می‌ماند.",
            "last_sync": None,
        },
    ]


def sync_ga4(days: int = 28) -> dict[str, Any]:
    """Fetch a compact GA4 snapshot. Optional SDK import keeps default install lightweight."""
    property_id = os.environ.get("GA4_PROPERTY_ID", "").strip()
    credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not property_id or not credentials:
        raise RuntimeError("GA4 is not configured")
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    except ImportError as exc:
        raise RuntimeError("GA4 connector dependencies are not installed; run: uv sync --group connectors") from exc

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=max(1, min(days, 365)) - 1)
    client = BetaAnalyticsDataClient()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="eventCount"),
            Metric(name="purchaseRevenue"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        limit=400,
    )
    response = client.run_report(request)
    rows = []
    for row in response.rows:
        rows.append({
            "date": row.dimension_values[0].value,
            "sessions": float(row.metric_values[0].value or 0),
            "users": float(row.metric_values[1].value or 0),
            "events": float(row.metric_values[2].value or 0),
            "purchase_revenue": float(row.metric_values[3].value or 0),
        })
    payload = {
        "source": "ga4",
        "property_id": property_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "synced_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "rows": rows,
        "totals": {
            "sessions": sum(r["sessions"] for r in rows),
            "users": sum(r["users"] for r in rows),
            "events": sum(r["events"] for r in rows),
            "purchase_revenue": sum(r["purchase_revenue"] for r in rows),
        },
    }
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    GA4_SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def ga4_snapshot() -> dict[str, Any] | None:
    if not GA4_SNAPSHOT.exists():
        return None
    try:
        return json.loads(GA4_SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
