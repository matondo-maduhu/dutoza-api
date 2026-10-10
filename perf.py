"""
Gzip compression ndogo bila dependency mpya.
Inapunguza feed.html (139KB) na JSON za feed hadi ~5x ndogo zaidi.
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


def init_compression(app):
    @app.after_request
    def compress_response(response):
        try:
            if (
                response.status_code != 200
                or response.direct_passthrough
                or "Content-Encoding" in response.headers
                or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
                or not (response.mimetype or "").startswith(COMPRESSIBLE)
            ):
                return response

            data = response.get_data()

            if len(data) < MIN_SIZE:
                return response

            compressed = gzip.compress(data, compresslevel=6)

            response.set_data(compressed)
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = str(len(compressed))
            response.headers.add("Vary", "Accept-Encoding")

        except Exception:
            # Compression isiwahi kuvunja response
            pass

        return response
