"""Session tokens for merchant/ops tenant scoping (ZB-001, ZB-030).

Opaque, HMAC-signed bearer tokens — no external deps, no server-side session
store (the token itself carries the claims; verification is a signature check).

Secret: ZARIN_SESSION_SECRET env var. If unset, a random secret is generated
once per process at import time — every token issued by this process becomes
invalid the moment the process restarts (fine for the demo; set the env var
explicitly for any deploy that must survive a restart or run multiple workers).

Enforcement is opt-in via ZARIN_REQUIRE_AUTH=1 (see config.REQUIRE_AUTH). With
it off (the default) this module is unused by the request path and the API
behaves exactly as before it existed — every merchant route still trusts the
`m=` query param, which is fine for the offline single-tenant judge demo.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from typing import Any

_SECRET = os.environ.get("ZARIN_SESSION_SECRET", "").encode() or secrets.token_bytes(32)
_SCOPES = ("merchant", "ops")


def _sign(payload: bytes) -> bytes:
    return hmac.new(_SECRET, payload, sha256).digest()


def issue(scope: str, merchant_key: str | None = None) -> str:
    """Issue an opaque bearer token bound to scope 'merchant' (+ merchant_key) or 'ops'."""
    if scope not in _SCOPES:
        raise ValueError(f"invalid scope: {scope!r}")
    claims = {"scope": scope, "merchant_key": merchant_key, "iat": int(time.time())}
    payload = json.dumps(claims, separators=(",", ":")).encode()
    sig = _sign(payload)
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def verify(token: str | None) -> dict[str, Any] | None:
    """Return the token's claims dict, or None if missing/malformed/tampered."""
    if not token or "." not in token:
        return None
    payload_b64, sig_b64 = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode())
        sig = base64.urlsafe_b64decode(sig_b64.encode())
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        claims = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or claims.get("scope") not in _SCOPES:
        return None
    return claims
