"""
PWA: manifest, service worker na ukurasa wa offline.

/sw.js lazima itoke root ("/") ili service worker ifunike app nzima.
"""

import json
import os

from flask import Blueprint, Response, render_template

pwa_bp = Blueprint("pwa", __name__)

_BASE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "id": "/feed",
    "name": "Incredibles",
    "short_name": "Incredibles",
    "description": "Quotes, muziki na jamii ya Incredibles.",
    "lang": "sw",
    "start_url": "/feed",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#f5f6f7",
    "theme_color": "#ffffff",
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "shortcuts": [
        {"name": "Tafuta", "url": "/search", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
        {"name": "Profile yangu", "url": "/profile", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
    ],
}


@pwa_bp.get("/manifest.webmanifest")
def manifest():
    return Response(
        json.dumps(MANIFEST, ensure_ascii=False),
        mimetype="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@pwa_bp.get("/sw.js")
def service_worker():
    with open(os.path.join(_BASE, "static", "sw.js"), "rb") as handle:
        body = handle.read()

    return Response(
        body,
        mimetype="application/javascript",
        headers={
            # Kivinjari kikague sasisho kila mara
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@pwa_bp.get("/offline")
def offline():
    return render_template("offline.html")
