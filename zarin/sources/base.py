"""DataSourceAdapter contract + the source registry the Control Center reads."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SourceStatus:
    id: str
    name_fa: str
    kind: str                      # "payment" | "web_analytics" | "crm" | ...
    configured: bool               # required env/creds present
    connected: bool                # can actually read data now
    status: str                    # "ok" | "not_configured" | "error"
    is_truth: bool = False         # True only for the payment source (source of financial truth)
    freshness: str | None = None   # ISO timestamp of latest data, when known
    note_fa: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class DataSourceAdapter(Protocol):
    id: str
    name_fa: str

    def status(self) -> SourceStatus: ...

    def metrics(self, f: str, t: str) -> dict | None:
        """Safe aggregate metrics for the window, or None when unavailable."""
        ...


def registry() -> list[DataSourceAdapter]:
    """All known adapters (configured or not). Import here to avoid cycles."""
    from .ga4 import GA4Adapter
    from .zarinpal import ZarinPalAdapter
    return [ZarinPalAdapter(), GA4Adapter()]
