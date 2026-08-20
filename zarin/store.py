"""Tiny append-only event log: durable JSONL + a bounded in-memory ring.

The Control Center reads aggregates from the ring (fast, no file I/O per request);
the JSONL gives durability and an audit trail. This is deliberately the *hackathon*
store — the production migration path (Postgres/ClickHouse/OTel) is in the ADRs.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, path: Path, maxlen: int = 5000, durable: bool = True):
        self.path = Path(path)
        self.durable = durable  # False → in-memory only (high-volume request telemetry)
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        if durable:
            self._warm()

    def _warm(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            self._buf.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

    def add(self, event: dict) -> dict:
        event.setdefault("ts", now_iso())
        with self._lock:
            self._buf.append(event)
            if not self.durable:
                return event
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                pass  # telemetry must never break the request path
        return event

    def recent(self, n: int | None = None) -> list[dict]:
        with self._lock:
            items = list(self._buf)
        return items[-n:] if n else items

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
