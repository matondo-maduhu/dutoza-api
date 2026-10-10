"""
Walinzi wa session: mtumiaji akizuiwa na admin (status != 'active'),
anatolewa hata kama alikuwa ameshaingia.

Ili kutoongeza mzigo kwenye DB, status ya mtumiaji inakaa kwenye cache
ya process kwa sekunde chache (TTL). Kama DB ina tatizo, mtumiaji
haondolewi (fail-open) - ili hitilafu ya DB isiwatoe watu wote.
"""

import time

from flask import jsonify, redirect, request, session, url_for

from db import get_connection

TTL_SECONDS = 60
ERROR_TTL_SECONDS = 10
BAD_STATUSES = {"blocked", "deactivated", "deleted", "suspended"}

_cache = {}  # user_id -> (expires_at, status | None)


def invalidate(user_id):
    """Futa cache ya mtumiaji (inaitwa admin anapobadilisha status)."""
    try:
        _cache.pop(int(user_id), None)
    except (TypeError, ValueError):
        pass


def _lookup_status(user_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT status FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else None

    except Exception:
        return "__error__"

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


def get_user_status(user_id):
    now = time.monotonic()
    cached = _cache.get(user_id)

    if cached and cached[0] > now:
        return cached[1]

    status = _lookup_status(user_id)

    if status == "__error__":
        _cache[user_id] = (now + ERROR_TTL_SECONDS, None)
        return None

    _cache[user_id] = (now + TTL_SECONDS, status)

    # Zuia cache isikue bila kikomo
    if len(_cache) > 5000:
        for key in [k for k, v in _cache.items() if v[0] <= now]:
            _cache.pop(key, None)

    return status


def init_user_guard(app):
    @app.before_request
    def block_banned_users():
        user_id = session.get("user_id")

        if not user_id:
            return None

        path = request.path

        if path.startswith("/static/") or path.startswith("/admin"):
            return None

        status = get_user_status(user_id)

        if status is None or status not in BAD_STATUSES:
            return None

        session.clear()

        if path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": "Akaunti yako imezuiwa."
            }), 401

        return redirect(url_for("user_auth.login"))
