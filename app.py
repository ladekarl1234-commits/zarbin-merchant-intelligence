"""Vercel Python entrypoint.

Vercel's Python runtime auto-detects `app.py` at the project root and serves the
top-level `app` ASGI object. Everything else (routing, static SPA, telemetry) is
the same FastAPI application that `uv run zarin` serves locally — there is no
Vercel-specific fork of the request path.
"""
from zarin.api import app  # noqa: F401  (re-exported: this IS the entrypoint symbol)
