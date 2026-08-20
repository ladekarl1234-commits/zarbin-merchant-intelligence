"""`uv run zarin` / `python -m zarin` — build marts if missing, then serve."""
from __future__ import annotations

import uvicorn

from .config import PORT
from .pipeline import ensure_built


def main() -> None:
    ensure_built()
    print(f"Zarbin (زرین‌بین) → http://localhost:{PORT}")
    uvicorn.run("zarin.api:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
