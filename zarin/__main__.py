"""`uv run zarin` / `python -m zarin` — build marts if missing, then serve."""
from __future__ import annotations

import uvicorn

from .config import HOST, PORT
from .pipeline import ensure_built


def main() -> None:
    ensure_built()
    url = f"http://localhost:{PORT}"
    bar = "─" * 46
    print(
        f"\n┌{bar}┐\n"
        f"│  Zarbin (زرین‌بین) — Merchant Intelligence   │\n"
        f"│                                              │\n"
        f"│  ▶ OPEN THE DASHBOARD:                        │\n"
        f"│    {url:<42}│\n"
        f"│                                              │\n"
        f"│  Best first demo: merchant M156 (Overview)   │\n"
        f"│  Ctrl+C to stop.                             │\n"
        f"└{bar}┘\n",
        flush=True,
    )
    uvicorn.run("zarin.api:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
