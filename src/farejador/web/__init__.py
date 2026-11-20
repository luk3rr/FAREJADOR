# Filename: __init__.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Serve the compiled dashboard from the same process as the API (FR-22, FR-23, ADR-3).

Only ``/`` (the page) and ``/assets/*`` (CSS, JavaScript, icon) are served here; everything else
keeps behaving as before. The dashboard is deliberately not mounted at ``/``: the 404 and 405 of
the rest of the service stay what they were, and ``/webhook`` and ``/healthz`` are untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

# Written by `npm run build` (ignored by git); the Docker build copies it in before installing.
DEFAULT_STATIC_DIR = Path(__file__).parent / "static"

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
    "object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    # Files are revalidated on every use (ETag and Last-Modified come from the file itself).
    "Cache-Control": "no-cache",
}


class _Assets(StaticFiles):
    """Static files that always carry the security headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(SECURITY_HEADERS)
        return response


def install_web(app: FastAPI, static_dir: Path | None = None) -> bool:
    """Add the dashboard to ``app``; return False (and warn) when it has not been built."""
    root = static_dir if static_dir is not None else DEFAULT_STATIC_DIR
    index = root / "index.html"
    assets = root / "assets"
    if not index.is_file() or not assets.is_dir():
        logger.warning(
            "dashboard not installed: no compiled files found",
            extra={"expected": str(root)},
        )
        return False

    pages = _Assets(directory=root, html=False)  # only ever asked for index.html

    async def page(request: Request) -> Response:
        # Same machinery as the assets: ETag, 304 on If-None-Match, HEAD, security headers.
        return await pages.get_response("index.html", request.scope)

    app.add_api_route("/", page, methods=["GET", "HEAD"], include_in_schema=False)
    app.mount("/assets", _Assets(directory=assets), name="dashboard-assets")
    return True
