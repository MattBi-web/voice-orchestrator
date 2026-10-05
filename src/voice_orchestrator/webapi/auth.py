"""Owner login for the hosted builder (blocco 6): one password, read-only
for everyone else.

`VOICE_ORCH_OWNER_PASSWORD` unset (local development, the test suite): no
login at all, every request may write — exactly as before. Set (the hosted
deployment): a visitor can read everything and use the demo features that
cost nothing or are already capped, and only a request carrying the owner's
session cookie may change anything.

The session is a stdlib-only signed cookie (expiry + HMAC-SHA256), no extra
dependency. The signing key is derived from the password itself, so
changing the password logs every existing session out.

Visitors may still POST to a few endpoints, listed in VISITOR_WRITES:
login itself, the voice test (`/api/voice/token` — the worker's daily
minutes cap still applies), the knowledge search preview (read-only), and
the try-it box (`/api/test/route`) and the multi-turn text test
(`/api/test/conversations…`, matched by prefix), which app.py pins to
FakeProvider for visitors so they never spend LLM tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Request

COOKIE_NAME = "vo_session"
SESSION_SECONDS = 7 * 24 * 3600

VISITOR_WRITES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/voice/token"),
    ("POST", "/api/knowledge/search"),
    ("POST", "/api/test/route"),
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def owner_password() -> str:
    """Read per call so tests (and a rotated secret) need no restart."""
    return os.environ.get("VOICE_ORCH_OWNER_PASSWORD", "")


def auth_required() -> bool:
    return bool(owner_password())


def _key() -> bytes:
    return hashlib.sha256(b"voice-orchestrator-session:" + owner_password().encode()).digest()


def make_token(now: float | None = None) -> str:
    expiry = int((now or time.time()) + SESSION_SECONDS)
    sig = hmac.new(_key(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def token_valid(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expiry, sig = token.split(".", 1)
    if not expiry.isdigit() or int(expiry) < (now or time.time()):
        return False
    expected = hmac.new(_key(), expiry.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def check_password(candidate: str) -> bool:
    pw = owner_password()
    return bool(pw) and hmac.compare_digest(candidate.encode(), pw.encode())


def is_owner(request: Request) -> bool:
    return not auth_required() or token_valid(request.cookies.get(COOKIE_NAME))


# Multi-turn text tests (fase B): create, take turns, end. Same footing as
# /api/test/route — FakeProvider only for visitors.
VISITOR_WRITE_PREFIXES = (
    ("POST", "/api/test/conversations"),
    ("DELETE", "/api/test/conversations/"),
)


def visitor_may(method: str, path: str) -> bool:
    if method in SAFE_METHODS or (method, path.rstrip("/")) in VISITOR_WRITES:
        return True
    return any(method == m and path.startswith(p) for m, p in VISITOR_WRITE_PREFIXES)
