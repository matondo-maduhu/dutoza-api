"""
Kasi: gzip kwa HTML/JSON/CSS/JS bila dependency mpya, na cache ndefu ya static.

- Kurasa na JSON: zinabanwa kwa kila ombi (level 6, haraka).
- CSS/JS za /static/: zinabanwa MARA MOJA na kuhifadhiwa kwenye kumbukumbu
  (kwa ETag), kwa sababu faili za static hazipiti njia ya kawaida ya kubana.
- /static/...?v=<toleo>: browser inaruhusiwa kuzihifadhi mwaka mzima
  (templating.asset() inabadilisha toleo faili ikibadilika).
"""

import gzip

from flask import request

COMPRESSIBLE = (
    "text/html",
    "text/css",
    "text/plain",
    "application/json",
    "application/javascript",
    "text/javascript",
    "image/svg+xml",
)

MIN_SIZE = 1024  # bytes
STATIC_CACHE_MAX_ENTRIES = 200
STATIC_CACHE_CONTROL = "public, max-age=31536000, immutable"

_static_gzip = {}  # (path, etag) -> bytes


def _compress_static(response):
    """Bana faili ya static (CSS/JS) na ihifadhi; rudisha bytes zilizobanwa."""
    data = response.get_data()

    if len(data) < MIN_SIZE:
        return None

    key = (request.path, response.headers.get("ETag"))
    cached = _static_gzip.get(key) if key[1] else None

    if cached is None:
        cached = gzip.compress(data, compresslevel=9)

        if key[1]:
            if len(_static_gzip) >= STATIC_CACHE_MAX_ENTRIES:
                _static_gzip.clear()

            _static_gzip[key] = cached

    return cached


def init_compression(app):
    @app.after_request
    def compress_response(response):
        try:
            if (
                response.status_code != 200
                or "Content-Encoding" in response.headers
                or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
                or not (response.mimetype or "").startswith(COMPRESSIBLE)
            ):
                return response

            if response.direct_passthrough:
                # Faili za static: zinabanwa tu CSS/JS/SVG za app yetu
                if not request.path.startswith("/static/"):
                    return response

                response.direct_passthrough = False
                compressed = _compress_static(response)

            else:
                data = response.get_data()
                compressed = (
                    gzip.compress(data, compresslevel=6)
                    if len(data) >= MIN_SIZE else None
                )

            if compressed is None:
                return response

            response.set_data(compressed)
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = str(len(compressed))
            response.headers.add("Vary", "Accept-Encoding")

        except Exception:
            # Compression isiwahi kuvunja response
            pass

        return response


def init_static_cache(app):
    @app.after_request
    def cache_versioned_static(response):
        if (
            response.status_code == 200
            and request.path.startswith("/static/")
            and request.args.get("v")
        ):
            response.headers["Cache-Control"] = STATIC_CACHE_CONTROL

        return response
