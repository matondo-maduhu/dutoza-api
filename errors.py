"""
Kurasa za hitilafu za Mercfy.

- Kurasa za kawaida (HTML): ukurasa mmoja safi wa Kiswahili (templates/error.html)
  badala ya ukurasa wa kawaida wa Flask.
- /api/... na maombi ya JSON: jibu la JSON lenye muundo uleule wa API zingine
  {"success": false, "error": ..., "message": ...}, ili watengenezaji wasiletewe HTML.

Kumbuka: ukurasa wa "502 Bad Gateway" wa Render hutoka kwa Render yenyewe wakati
app haijibu kabisa (inaamka au imezimika). Flask haiwezi kuubadilisha, kwa sababu
wakati huo app haifanyi kazi. Hapa tunashughulikia makosa ambayo app yenyewe inayatoa.
"""

import logging

from flask import Response, jsonify, render_template, request, url_for
from werkzeug.exceptions import HTTPException

log = logging.getLogger("mercfy.errors")

# Namba ya hitilafu -> aina ya ukurasa (angalia templates/error.html)
VARIANTS = {
    401: "forbidden",
    403: "forbidden",
    404: "notfound",
    429: "busy",
    502: "server",
    503: "server",
    504: "server",
}

API_MESSAGES = {
    "forbidden": "Huruhusiwi kufikia rasilimali hii.",
    "notfound": "Rasilimali hii haipo.",
    "busy": "Maombi ni mengi sana. Subiri kidogo kisha ujaribu tena.",
    "server": "Seva haipatikani kwa sasa. Jaribu tena baada ya sekunde chache.",
    "error": "Ombi halikukamilika.",
}

NO_BODY_PREFIXES = ("/static/",)
NO_BODY_PATHS = ("/favicon.ico", "/sw.js.map")


def _wants_json():
    return (
        request.path == "/api"
        or request.path.startswith("/api/")
        or request.is_json
        or "application/json" in request.headers.get("Accept", "")
    )


def _retry_path(fallback):
    """Njia ya kujaribu tena: ukurasa ule ule (GET tu) na ndani ya tovuti hii tu."""
    if request.method not in ("GET", "HEAD"):
        return fallback

    path = request.full_path.rstrip("?")

    if (
        not path.startswith("/")
        or path.startswith("//")
        or path.startswith("/\\")
        or len(path) > 2000
    ):
        return fallback

    return path


def render_error_page(variant, code="", retry_url=None):
    home_url = url_for("user_feed.feed")

    return render_template(
        "error.html",
        variant=variant,
        code=code,
        home_url=home_url,
        login_url=url_for("user_auth.login"),
        retry_url=retry_url or home_url,
    )


def init_errors(app):
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        # Majibu yaliyokwisha kutengenezwa (mf. abort(redirect(...))) hayaguswi
        if getattr(error, "response", None) is not None:
            return error.response

        code = error.code or 500
        variant = VARIANTS.get(code, "error")

        if request.path.startswith(NO_BODY_PREFIXES) or request.path in NO_BODY_PATHS:
            response = Response("", status=code)
        elif _wants_json():
            response = jsonify({
                "success": False,
                "error": error.name,
                "message": API_MESSAGES[variant],
            })
            response.status_code = code
        else:
            if code >= 500:
                log.error(
                    "Hitilafu %s kwenye %s %s",
                    code,
                    request.method,
                    request.path,
                    exc_info=getattr(error, "original_exception", None),
                )

            html = render_error_page(
                variant,
                code=code,
                retry_url=_retry_path(url_for("user_feed.feed")),
            )
            response = Response(html, status=code, mimetype="text/html")

        # Vichwa vya ziada vya hitilafu (mf. Allow kwenye 405, Retry-After)
        try:
            for name, value in error.get_headers():
                if name.lower() not in ("content-type", "content-length"):
                    response.headers[name] = value
        except Exception:
            pass

        if variant in ("server", "busy"):
            response.headers.setdefault("Retry-After", "10")

        response.headers["Cache-Control"] = "no-store"
        return response
