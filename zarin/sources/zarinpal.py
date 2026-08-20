"""ZarinPal payment source — the source of financial truth. Wraps the local marts."""
from __future__ import annotations

from datetime import UTC, datetime

from ..config import MARTS_DIR
from ..db import q1
from .base import SourceStatus


class ZarinPalAdapter:
    id = "zarinpal"
    name_fa = "پرداخت زرین‌پال"

    def status(self) -> SourceStatus:
        marts = MARTS_DIR / "sessions.parquet"
        connected = marts.exists()
        freshness = None
        if connected:
            freshness = datetime.fromtimestamp(marts.stat().st_mtime, UTC).isoformat(timespec="seconds")
        return SourceStatus(
            id=self.id, name_fa=self.name_fa, kind="payment", is_truth=True,
            configured=True, connected=connected,
            status="ok" if connected else "error",
            freshness=freshness,
            note_fa="منبع حقیقتِ مالی. همه مبالغ و نرخ‌های تبدیل از این منبع می‌آیند.",
            error=None if connected else "marts not built — run `uv run python -m zarin.pipeline`",
        )

    def metrics(self, f: str, t: str) -> dict | None:
        r = q1("""
            SELECT count(*) AS sessions,
                   count(*) FILTER (WHERE outcome='verified') AS verified,
                   sum(amount) FILTER (WHERE outcome='verified') AS gmv
            FROM sessions WHERE d BETWEEN $f AND $t""", {"f": f, "t": t})
        if not r or not r.get("sessions"):
            return None
        sessions = r["sessions"] or 0
        verified = r["verified"] or 0
        return {
            "sessions": sessions, "verified": verified,
            "gmv": r["gmv"] or 0,
            "conv": (verified / sessions) if sessions else None,
        }
