"""
Ulinzi wa jumla wa app:

1. Cookies za session: HttpOnly, SameSite=Lax, na Secure (isipokuwa kwenye debug).
2. Ukaguzi wa chanzo cha ombi (CSRF): ombi la kubadilisha data linalotumia
   cookie ya session LAZIMA litoke kwenye tovuti hii hii. Hii inalinda fomu na
   fetch zote za watumiaji, developers na admin bila kubadilisha templates.
   Maombi yenye `Authorization: Bearer` (API keys za developers) hayahusiki,
   kwa sababu hayatumii cookie na tovuti nyingine haiwezi kuongeza header hiyo.
3. Headers za usalama (nosniff, kuzuia iframe, referrer, HSTS kwenye HTTPS).
4. Onyo kama FLASK_SECRET_KEY haijawekwa.
"""

import logging
import os
from urllib.parse import urlparse

from flask import Response, jsonify, request

log = logging.getLogger("mercfy.security")

DEFAULT_SECRET = "change-this-secret-in-production"
MIN_SECRET_LENGTH = 16
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

BLOCKED_MESSAGE = (
    "Ombi limekataliwa kwa sababu za usalama. "
    "Onyesha ukurasa upya kisha ujaribu tena."
)


def secret_key_is_weak(app):
    key = app.secret_key

    return not key or key == DEFAULT_SECRET or len(str(key)) < MIN_SECRET_LENGTH


def _host_of(value):
    try:
        return urlparse(value).netloc.lower()
    except ValueError:
        return ""


def is_same_origin():
    """True kama ombi limetoka kwenye tovuti hii (si tovuti nyingine)."""
    site = request.headers.get("Sec-Fetch-Site")

    if site:
        return site in ("same-origin", "none")

    host = request.host.lower()
    origin = request.headers.get("Origin")

    if origin is not None:
        return origin != "null" and _host_of(origin) == host

    referer = request.headers.get("Referer")

    if referer:
        return _host_of(referer) == host

    return False


def init_security(app):
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    secure = (not debug) and os.getenv("SESSION_COOKIE_SECURE", "1") != "0"

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=secure,
    )

    @app.before_request
    def reject_cross_site_writes():
        if request.method in SAFE_METHODS:
            return None

        if request.headers.get("Authorization", "")[:7].lower() == "bearer ":
            return None

        if is_same_origin():
            return None

        log.warning(
            "Ombi la kubadilisha data limekataliwa (chanzo si sahihi): %s %s origin=%r site=%r",
            request.method,
            request.path,
            request.headers.get("Origin"),
            request.headers.get("Sec-Fetch-Site"),
        )

        wants_json = (
            request.path.startswith("/api/")
            or request.is_json
            or "application/json" in request.headers.get("Accept", "")
        )

        if wants_json:
            return jsonify({
                "success": False,
                "error": "Cross-site request blocked",
                "message": BLOCKED_MESSAGE,
            }), 403

        return Response(
            "<!DOCTYPE html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<body style='font-family:system-ui;padding:24px;max-width:480px;margin:auto'>"
            "<h2>Ombi limekataliwa</h2><p>" + BLOCKED_MESSAGE + "</p>"
            "<p><a href='/'>Rudi mwanzo</a></p></body>",
            status=403,
            mimetype="text/html",
        )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        if request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")

        return response

    if secret_key_is_weak(app):
        log.warning(
            "ONYO: FLASK_SECRET_KEY haijawekwa au ni fupi/ya msingi. "
            "Mtu anaweza kughushi session. Weka thamani ndefu ya siri kwenye environment variables."
        )
