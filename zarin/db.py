"""DuckDB access layer. Marts are registered as views; queries return dict rows."""
from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb

from .config import MARTS_DIR

_MARTS = ("sessions", "attempts", "merchant_daily", "customers", "merchant_stats")
_lock = threading.RLock()  # reentrant: q() calls connect() while holding it
_con: duckdb.DuckDBPyConnection | None = None


def connect() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            con = duckdb.connect()
            for m in _MARTS:
                p = (MARTS_DIR / f"{m}.parquet").as_posix()
                con.execute(f"CREATE VIEW {m} AS SELECT * FROM read_parquet('{p}')")
            _con = con
        return _con


def reset() -> None:
    """Testing hook: drop the cached connection so a new MARTS_DIR takes effect."""
    global _con
    with _lock:
        _con = None


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


def q(sql: str, params: list | dict | None = None) -> list[dict[str, Any]]:
    """Run SQL against the marts, return list of dicts (JSON-safe scalars)."""
    with _lock:
        cur = connect().execute(sql, params if params is not None else [])
        cols = [d[0] for d in cur.description]
        return [{c: _plain(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def q1(sql: str, params: list | dict | None = None) -> dict[str, Any]:
    rows = q(sql, params)
    return rows[0] if rows else {}
