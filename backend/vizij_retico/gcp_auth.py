"""Application Default Credentials for the Vertex AI provider.

Vertex differs from the AI Studio Gemini API in the one way that matters here: it
authenticates with a short-lived OAuth token rather than a static API key. That is a
feature for a deployed demo — on Cloud Run the runtime service account supplies the
token, so there is no key to mount, rotate or leak, and usage bills to the project's
ordinary Cloud billing account instead of AI Studio prepayment credits.

The cost is that a token expires (~1 hour), so it has to be refreshed rather than read
once at startup — a long-lived process would otherwise start 401ing an hour in.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

# Refresh a little early: a token that expires mid-request is indistinguishable from a
# permissions problem, and this is a real-time loop with no room to retry politely.
_SKEW_SECONDS = 300

_lock = threading.Lock()
_credentials = None
_project: Optional[str] = None


def available() -> tuple[bool, str]:
    """(usable, reason) — whether ADC can currently mint a Vertex token."""
    try:
        import google.auth  # noqa: F401
    except ImportError:
        return False, "google-auth not installed"
    try:
        _, project = _load()
    except Exception as exc:  # no ADC configured, no metadata server, etc.
        return False, str(exc).split("\n")[0][:120]
    if not project:
        return False, "no project — set VERTEX_PROJECT"
    return True, project


def _load():
    """Cache the credentials object itself; it knows how to refresh in place."""
    global _credentials, _project
    if _credentials is None:
        import google.auth

        _credentials, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    return _credentials, _project


def project() -> str:
    try:
        return _load()[1] or ""
    except Exception:
        return ""


def token() -> str:
    """A currently-valid access token, refreshed when close to expiry."""
    import google.auth.transport.requests

    with _lock:
        creds, _ = _load()
        expiry = getattr(creds, "expiry", None)
        stale = True
        if creds.valid and expiry is not None:
            stale = (expiry.timestamp() - time.time()) < _SKEW_SECONDS
        elif creds.valid:
            stale = False
        if stale:
            creds.refresh(google.auth.transport.requests.Request())
        return creds.token or ""
