"""DuckDB access layer. Marts are registered as views; queries return dict rows."""
from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb

from .config import MARTS_DIR

_MARTS = ("sessions", "attempts", "merchant_daily", "customers", "merchant_stats")
_init_lock = threading.Lock()  # guards one-time connect() only — queries run lock-free (ZB-002)
_con: duckdb.DuckDBPyConnection | None = None
_local = threading.local()  # one cursor per thread: DuckDB cursors read concurrently, the
                             # shared connection object itself is not thread-safe for execute()


# columns that must exist in the marts for this code version — detects stale parquet
# built by an older pipeline (e.g. before the `reversed` column) and fails with a clear
# instruction instead of a bare DuckDB Binder Error 500 on every endpoint.
_SCHEMA_GUARD = {"merchant_daily": "reversed", "sessions": "recovered"}


def connect() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        with _init_lock:
            if _con is None:  # double-checked: only the first thread through does the work
                con = duckdb.connect()
                # ponytail: fixed per-connection thread budget so several concurrent
                # cursors don't each try to claim every core; raise if one query needs
                # more raw throughput than concurrency.
                con.execute("PRAGMA threads=4")
                for m in _MARTS:
                    p = (MARTS_DIR / f"{m}.parquet").as_posix()
                    con.execute(f"CREATE VIEW {m} AS SELECT * FROM read_parquet('{p}')")
                for mart, col in _SCHEMA_GUARD.items():
                    try:
                        con.execute(f"SELECT {col} FROM {mart} LIMIT 0")
                    except duckdb.Error as e:
                        raise RuntimeError(
                            f"marts are stale (missing {mart}.{col}). "
                            "Rebuild them: `uv run python -m zarin.pipeline`"
                        ) from e
                _con = con
    return _con


def _cursor() -> duckdb.DuckDBPyConnection:
    cur = getattr(_local, "cur", None)
    if cur is None:
        cur = connect().cursor()
        _local.cur = cur
    return cur


def reset() -> None:
    """Testing hook: drop the cached connection so a new MARTS_DIR takes effect.

    Clears this thread's cursor too. Other threads' cached cursors (if any) are
    orphaned rather than actively closed — fine for the single-threaded test suite
    this hook exists for; a long-lived multi-threaded server never calls reset().
    """
    global _con
    with _init_lock:
        _con = None
    if hasattr(_local, "cur"):
        del _local.cur
    invalidate_derived()


def invalidate_derived() -> None:
    """Drop everything memoised *over* the marts.

    Swapping MARTS_DIR without this leaves the response cache and every lru_cache
    answering from the previous dataset — `reset()` would look like it worked and
    quietly serve stale money. Imports are local because these modules import db.
    """
    return
    from . import api, cache, control, copilot, insights
    cache.clear()
    for fn in (control.platform, control.merchants, control.sources, control._dq_sidecar,
               insights._platform_floors, copilot._plan,
               api.meta, api.quality, api._cached_eval):
        fn.cache_clear()


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
    cur = _cursor().execute(sql, params if params is not None else [])
    cols = [d[0] for d in cur.description]
    return [{c: _plain(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def q1(sql: str, params: list | dict | None = None) -> dict[str, Any]:
    rows = q(sql, params)
    return rows[0] if rows else {}
