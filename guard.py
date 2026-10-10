"""
Walinzi wa session.

1) Mtumiaji akizuiwa na admin (status != 'active'), anatolewa hata kama
   alikuwa ameshaingia.
2) Developer akisimamishwa ('suspended'), anatolewa kwenye /developers/*.
   (API keys zake pia zinazimwa na admin, kwa hiyo API haifanyi kazi.)

Ili kutoongeza mzigo kwenye DB, status inakaa kwenye cache ya process kwa
muda mfupi (TTL). Kama DB ina tatizo, hakuna anayeondolewa (fail-open) -
ili hitilafu ya DB isiwatoe watu wote.
"""

import time

from flask import flash, jsonify, redirect, request, session, url_for

from db import get_connection

TTL_SECONDS = 60
ERROR_TTL_SECONDS = 10
BAD_USER_STATUSES = {"blocked", "deactivated", "deleted", "suspended"}
BAD_DEVELOPER_STATUSES = {"suspended"}

# jina la table linatoka kwenye whitelist hii tu
_TABLES = {"users", "developers"}

_cache = {"users": {}, "developers": {}}  # id -> (expires_at, status | None)


def _invalidate(table, row_id):
    try:
        _cache[table].pop(int(row_id), None)
    except (TypeError, ValueError):
        pass


def invalidate(user_id):
    """Futa cache ya mtumiaji (inaitwa admin anapobadilisha status)."""
    _invalidate("users", user_id)


def invalidate_developer(developer_id):
    _invalidate("developers", developer_id)


def _lookup_status(table, row_id):
    if table not in _TABLES:
        return "__error__"

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(f"SELECT status FROM {table} WHERE id = %s", (row_id,))
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


def _get_status(table, row_id):
    store = _cache[table]
    now = time.monotonic()
    cached = store.get(row_id)

    if cached and cached[0] > now:
        return cached[1]

    status = _lookup_status(table, row_id)

    if status == "__error__":
        store[row_id] = (now + ERROR_TTL_SECONDS, None)
        return None

    store[row_id] = (now + TTL_SECONDS, status)

    # Zuia cache isikue bila kikomo
    if len(store) > 5000:
        for key in [k for k, v in store.items() if v[0] <= now]:
            store.pop(key, None)

    return status


def get_user_status(user_id):
    return _get_status("users", user_id)


def get_developer_status(developer_id):
    return _get_status("developers", developer_id)


def init_user_guard(app):
    @app.before_request
    def block_banned_sessions():
        path = request.path

        if path.startswith("/static/") or path.startswith("/admin"):
            return None

        # ---- Developers ----
        developer_id = session.get("developer_id")

        if developer_id and path.startswith("/developers"):
            status = get_developer_status(developer_id)

            if status in BAD_DEVELOPER_STATUSES:
                session.clear()
                flash("Akaunti yako ya developer imesimamishwa. Wasiliana na admin.")
                return redirect(url_for("developers.login"))

        # ---- Watumiaji wa app ----
        user_id = session.get("user_id")

        if not user_id:
            return None

        status = get_user_status(user_id)

        if status is None or status not in BAD_USER_STATUSES:
            return None

        session.clear()

        if path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": "Akaunti yako imezuiwa."
            }), 401

        return redirect(url_for("user_auth.login"))
