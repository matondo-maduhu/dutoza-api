"""
Admin panel mpya: Muhtasari, Quotes (grid ya kuandika + CSV), Maudhui,
Reports na Users.

Kanuni za usalama/utulivu:
- Kila route inahitaji admin aliyeingia (admin_logged_in).
- Kila POST inakaguliwa na CSRF token.
- Majina ya table hayatoki kwa mtumiaji - yanatoka kwenye whitelist (CONTENT).
- Hakuna kitu kinachofutwa: maudhui "yanafichwa" (status='hidden') na yanaweza
  kurudishwa.
"""

import csv
import io
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from math import ceil

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import guard
from admin import admin_logged_in, safe_close, slugify
from db import get_connection

panel_bp = Blueprint("panel", __name__)

PER_PAGE = 20
MAX_IMPORT_ROWS = 1000
MAX_QUOTE_LENGTH = 5000

# Whitelist ya maudhui yanayosimamiwa (jina la table halitoki kwa user)
CONTENT = {
    "quote": {"table": "quotes", "preview": "t.text", "label": "Quotes", "icon": "💬"},
    "music": {"table": "songs", "preview": "t.title", "label": "Muziki", "icon": "🎵"},
    "post": {"table": "posts", "preview": "t.content", "label": "Posts", "icon": "📝"},
}

USER_STATUSES = ["all", "active", "blocked", "deactivated", "deleted"]


# ============================================================
# HELPERS
# ============================================================

@contextmanager
def db_cursor(commit=False):
    """Cursor salama: inafunga connection, na ina-rollback kukiwa na hitilafu."""
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()
        yield cursor

        if commit:
            connection.commit()

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        raise

    finally:
        safe_close(connection)


def safe_rollback(cursor):
    try:
        cursor.connection.rollback()
    except Exception:
        pass


def wants_json():
    return request.path.endswith("/import") or request.is_json


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not admin_logged_in():
            if wants_json():
                return jsonify({"ok": False, "error": "Login required"}), 401
            return redirect(url_for("admin.admin_login"))
        return view(*args, **kwargs)

    return wrapper


def csrf_token():
    token = session.get("admin_csrf")

    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf"] = token

    return token


def csrf_ok():
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("admin_csrf") or ""

    return bool(expected) and secrets.compare_digest(sent, expected)


def csrf_protected(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not csrf_ok():
            if wants_json():
                return jsonify({"ok": False, "error": "Session imeisha. Onyesha ukurasa upya."}), 400
            flash("Session imeisha. Jaribu tena.", "error")
            return redirect(safe_next(request.form.get("next")) or url_for("panel.overview"))
        return view(*args, **kwargs)

    return wrapper


def safe_next(value):
    """Ruhusu redirect za ndani ya /admin tu (epuka open-redirect)."""
    if value and value.startswith("/admin") and not value.startswith("//"):
        return value
    return None


def like_param(text):
    """Tengeneza pattern ya LIKE salama (escape % _ \\)."""
    escaped = (
        text.lower()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def paginate(total, page, per_page=PER_PAGE):
    pages = max(1, ceil(total / per_page))
    page = max(1, min(page, pages))

    return {
        "page": page,
        "pages": pages,
        "total": total,
        "per_page": per_page,
        "offset": (page - 1) * per_page,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def audit(action, target_type=None, target_id=None, detail=None):
    """Rekodi ya shughuli ya admin. Haivunji kitendo kikuu ikishindwa."""
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO admin_audit_log (action, target_type, target_id, detail)
                VALUES (%s, %s, %s, %s)
                """,
                (action, target_type, target_id, (detail or "")[:500] or None),
            )
    except Exception:
        pass


_badge_cache = {"at": 0.0, "value": 0}


def open_reports_count():
    """Idadi ya reports wazi kwa badge ya sidebar (cache ya sekunde 20)."""
    now = time.monotonic()

    if now - _badge_cache["at"] < 20:
        return _badge_cache["value"]

    value = 0

    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM content_reports WHERE status = 'open'")
            value = cursor.fetchone()[0]
    except Exception:
        value = 0

    _badge_cache["at"] = now
    _badge_cache["value"] = value

    return value


def invalidate_badge():
    _badge_cache["at"] = 0.0


@panel_bp.app_context_processor
def inject_panel_helpers():
    # Hizi ni functions - hazigusi DB mpaka template ya admin iziite
    return {"panel_csrf": csrf_token, "panel_open_reports": open_reports_count}


@panel_bp.app_template_filter("fmt_dt")
def fmt_dt(value, fmt="%d %b %Y, %H:%M"):
    if not value:
        return "-"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace(" ", "T")[:19])
        except ValueError:
            return value

    try:
        return value.strftime(fmt)
    except Exception:
        return str(value)


def page_url(**overrides):
    """URL ya ukurasa huu huu na vigezo vilivyobadilishwa (kwa pagination/filters)."""
    args = request.args.to_dict()
    args.update({k: v for k, v in overrides.items() if v is not None})

    for key in [k for k, v in overrides.items() if v is None]:
        args.pop(key, None)

    return url_for(request.endpoint, **args)


@panel_bp.app_context_processor
def inject_page_url():
    return {"page_url": page_url}


# ============================================================
# MUHTASARI (OVERVIEW)
# ============================================================

SW_DAYS = ["Jtt", "Jne", "Jtn", "Alh", "Iju", "Jmo", "Jpi"]  # Jumatatu = 0

STATS = [
    ("users_total", "SELECT COUNT(*) FROM users"),
    ("users_active", "SELECT COUNT(*) FROM users WHERE status = 'active'"),
    ("users_blocked", "SELECT COUNT(*) FROM users WHERE status = 'blocked'"),
    ("quotes_total", "SELECT COUNT(*) FROM quotes"),
    ("quotes_hidden", "SELECT COUNT(*) FROM quotes WHERE status = 'hidden'"),
    ("songs_total", "SELECT COUNT(*) FROM songs"),
    ("songs_hidden", "SELECT COUNT(*) FROM songs WHERE status = 'hidden'"),
    ("posts_total", "SELECT COUNT(*) FROM posts"),
    ("comments_total", "SELECT COUNT(*) FROM post_comments"),
    ("plays_total", "SELECT COALESCE(SUM(play_count), 0) FROM songs"),
    ("likes_total", "SELECT COUNT(*) FROM content_likes"),
    ("reports_open", "SELECT COUNT(*) FROM content_reports WHERE status = 'open'"),
    ("categories_total", "SELECT COUNT(*) FROM categories"),
    ("api_keys_total", "SELECT COUNT(*) FROM api_keys"),
    ("developers_total", "SELECT COUNT(*) FROM developers"),
]


def _daily_counts(cursor, table, since):
    """{ 'YYYY-MM-DD': count } kwa siku 7 zilizopita."""
    try:
        cursor.execute(
            f"""
            SELECT DATE(created_at), COUNT(*)
            FROM {table}
            WHERE created_at >= %s
            GROUP BY DATE(created_at)
            """,
            (since,),
        )
        return {str(row[0])[:10]: row[1] for row in cursor.fetchall()}
    except Exception:
        safe_rollback(cursor)
        return {}


@panel_bp.get("/admin/overview")
@admin_required
def overview():
    stats = {key: 0 for key, _ in STATS}
    chart = []
    recent_users = []
    recent_reports = []
    recent_audit = []

    try:
        with db_cursor() as cursor:
            for key, sql in STATS:
                try:
                    cursor.execute(sql)
                    stats[key] = cursor.fetchone()[0] or 0
                except Exception:
                    safe_rollback(cursor)

            # Chati ya siku 7
            today = datetime.now(timezone.utc).date()
            days = [today - timedelta(days=i) for i in range(6, -1, -1)]
            since = datetime.combine(days[0], datetime.min.time())

            new_users = _daily_counts(cursor, "users", since)
            new_quotes = _daily_counts(cursor, "quotes", since)
            new_songs = _daily_counts(cursor, "songs", since)

            for day in days:
                key = day.isoformat()
                chart.append({
                    "label": SW_DAYS[day.weekday()],
                    "date": day.strftime("%d %b"),
                    "users": new_users.get(key, 0),
                    "content": new_quotes.get(key, 0) + new_songs.get(key, 0),
                })

            try:
                cursor.execute(
                    """
                    SELECT id, full_name, username, status, created_at
                    FROM users
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5
                    """
                )
                recent_users = cursor.fetchall()
            except Exception:
                safe_rollback(cursor)

            try:
                cursor.execute(
                    """
                    SELECT id, content_type, content_id, reason, created_at
                    FROM content_reports
                    WHERE status = 'open'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5
                    """
                )
                recent_reports = cursor.fetchall()
            except Exception:
                safe_rollback(cursor)

            try:
                cursor.execute(
                    """
                    SELECT action, target_type, target_id, detail, created_at
                    FROM admin_audit_log
                    ORDER BY created_at DESC, id DESC
                    LIMIT 8
                    """
                )
                recent_audit = cursor.fetchall()
            except Exception:
                safe_rollback(cursor)

    except Exception as error:
        flash(f"Imeshindikana kupakia takwimu: {error}", "error")

    chart_max = max([1] + [max(d["users"], d["content"]) for d in chart])

    return render_template(
        "admin/panel_overview.html",
        active="overview",
        stats=stats,
        chart=chart,
        chart_max=chart_max,
        recent_users=recent_users,
        recent_reports=recent_reports,
        recent_audit=recent_audit,
        content_types=CONTENT,
    )


# ============================================================
# USERS
# ============================================================

@panel_bp.get("/admin/users")
@admin_required
def users_page():
    status = request.args.get("status", "all")
    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)

    if status not in USER_STATUSES:
        status = "all"

    where = []
    params = []

    if status != "all":
        where.append("u.status = %s")
        params.append(status)

    if search:
        pattern = like_param(search)
        where.append(
            "(LOWER(u.username) LIKE %s ESCAPE '\\' "
            "OR LOWER(u.full_name) LIKE %s ESCAPE '\\' "
            "OR LOWER(u.email) LIKE %s ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = []
    counts = {}
    pager = paginate(0, 1)

    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) FROM users GROUP BY status")
            counts = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(f"SELECT COUNT(*) FROM users u {where_sql}", params)
            pager = paginate(cursor.fetchone()[0], page)

            cursor.execute(
                f"""
                SELECT
                    u.id, u.full_name, u.username, u.email,
                    u.profile_image_url, u.status, u.created_at,
                    (SELECT COUNT(*) FROM quotes q WHERE q.user_id = u.id),
                    (SELECT COUNT(*) FROM songs s WHERE s.user_id = u.id)
                FROM users u
                {where_sql}
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [pager["per_page"], pager["offset"]],
            )
            rows = cursor.fetchall()

    except Exception as error:
        flash(f"Imeshindikana kupakia users: {error}", "error")

    counts["all"] = sum(counts.values())

    return render_template(
        "admin/panel_users.html",
        active="users",
        users=rows,
        counts=counts,
        statuses=USER_STATUSES,
        status=status,
        search=search,
        pager=pager,
    )


@panel_bp.post("/admin/users/<int:user_id>/status")
@admin_required
@csrf_protected
def user_set_status(user_id):
    action = request.form.get("action", "")
    back = safe_next(request.form.get("next")) or url_for("panel.users_page")

    if action not in ("block", "unblock"):
        flash("Kitendo si sahihi.", "error")
        return redirect(back)

    new_status = "blocked" if action == "block" else "active"
    allowed_from = ("active", "deactivated") if action == "block" else ("blocked",)

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT username, status FROM users WHERE id = %s", (user_id,)
            )
            row = cursor.fetchone()

            if not row:
                flash("Mtumiaji hajapatikana.", "error")
                return redirect(back)

            username, current = row

            if current not in allowed_from:
                flash(
                    f"@{username} ana status '{current}', kitendo hakiwezekani.",
                    "error",
                )
                return redirect(back)

            cursor.execute(
                "UPDATE users SET status = %s WHERE id = %s", (new_status, user_id)
            )

        guard.invalidate(user_id)
        audit(action, "user", user_id, f"@{username}")

        if action == "block":
            flash(f"@{username} amezuiwa. Maudhui yake yamefichwa kwenye feed.", "success")
        else:
            flash(f"@{username} amerudishwa.", "success")

    except Exception as error:
        flash(f"Imeshindikana: {error}", "error")

    return redirect(back)


# ============================================================
# MAUDHUI (MODERATION)
# ============================================================

@panel_bp.get("/admin/content")
@admin_required
def content_page():
    ctype = request.args.get("type", "quote")
    status = request.args.get("status", "all")
    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)

    if ctype not in CONTENT:
        ctype = "quote"

    if status not in ("all", "published", "hidden"):
        status = "all"

    cfg = CONTENT[ctype]
    table = cfg["table"]
    preview = cfg["preview"]

    where = []
    params = []

    if status != "all":
        where.append("t.status = %s")
        params.append(status)

    if search:
        pattern = like_param(search)
        where.append(
            f"(LOWER({preview}) LIKE %s ESCAPE '\\' "
            "OR LOWER(u.username) LIKE %s ESCAPE '\\')"
        )
        params.extend([pattern, pattern])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    items = []
    pager = paginate(0, 1)

    try:
        with db_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {table} t
                LEFT JOIN users u ON u.id = t.user_id
                {where_sql}
                """,
                params,
            )
            pager = paginate(cursor.fetchone()[0], page)

            cursor.execute(
                f"""
                SELECT
                    t.id, {preview}, t.status, t.created_at, t.user_id,
                    u.username, u.full_name,
                    (SELECT COUNT(*) FROM content_reports r
                      WHERE r.content_type = %s
                        AND r.content_id = t.id
                        AND r.status = 'open')
                FROM {table} t
                LEFT JOIN users u ON u.id = t.user_id
                {where_sql}
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT %s OFFSET %s
                """,
                [ctype] + params + [pager["per_page"], pager["offset"]],
            )
            items = cursor.fetchall()

    except Exception as error:
        flash(f"Imeshindikana kupakia maudhui: {error}", "error")

    return render_template(
        "admin/panel_content.html",
        active="content",
        items=items,
        ctype=ctype,
        content_types=CONTENT,
        status=status,
        search=search,
        pager=pager,
    )


@panel_bp.post("/admin/content/<ctype>/<int:content_id>/status")
@admin_required
@csrf_protected
def content_set_status(ctype, content_id):
    back = safe_next(request.form.get("next")) or url_for("panel.content_page", type=ctype)
    action = request.form.get("action", "")

    if ctype not in CONTENT or action not in ("hide", "restore"):
        flash("Ombi si sahihi.", "error")
        return redirect(back)

    table = CONTENT[ctype]["table"]
    new_status = "hidden" if action == "hide" else "published"

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                f"UPDATE {table} SET status = %s WHERE id = %s", (new_status, content_id)
            )

            if cursor.rowcount == 0:
                flash("Maudhui hayajapatikana.", "error")
                return redirect(back)

        audit(action, ctype, content_id)
        flash(
            "Maudhui yamefichwa." if action == "hide" else "Maudhui yamerudishwa.",
            "success",
        )

    except Exception as error:
        flash(
            f"Imeshindikana: {error}. "
            "(Kama ni kuhusu 'status', database yako inaweza kuwa na kikomo cha thamani zinazoruhusiwa.)",
            "error",
        )

    return redirect(back)


# ============================================================
# REPORTS
# ============================================================

@panel_bp.get("/admin/reports")
@admin_required
def reports_page():
    status = request.args.get("status", "open")
    page = request.args.get("page", 1, type=int)

    if status not in ("open", "resolved", "all"):
        status = "open"

    where_sql = "" if status == "all" else "WHERE r.status = %s"
    params = [] if status == "all" else [status]

    rows = []
    counts = {"open": 0, "resolved": 0}
    pager = paginate(0, 1)

    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) FROM content_reports GROUP BY status")
            for key, value in cursor.fetchall():
                counts[key] = value

            cursor.execute(f"SELECT COUNT(*) FROM content_reports r {where_sql}", params)
            pager = paginate(cursor.fetchone()[0], page)

            cursor.execute(
                f"""
                SELECT
                    r.id, r.content_type, r.content_id, r.reason, r.created_at,
                    r.status, r.resolution, r.resolved_at,
                    ru.username,
                    COALESCE(q.text, s.title, p.content),
                    COALESCE(q.status, s.status, p.status),
                    COALESCE(q.user_id, s.user_id, p.user_id),
                    au.username,
                    au.status
                FROM content_reports r
                LEFT JOIN users ru ON ru.id = r.reporter_id
                LEFT JOIN quotes q ON r.content_type = 'quote' AND q.id = r.content_id
                LEFT JOIN songs  s ON r.content_type = 'music' AND s.id = r.content_id
                LEFT JOIN posts  p ON r.content_type = 'post'  AND p.id = r.content_id
                LEFT JOIN users au ON au.id = COALESCE(q.user_id, s.user_id, p.user_id)
                {where_sql}
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [pager["per_page"], pager["offset"]],
            )
            rows = cursor.fetchall()

    except Exception as error:
        flash(
            f"Imeshindikana kupakia reports: {error}. "
            "Fungua Schema Status na uendeshe schema upya.",
            "error",
        )

    return render_template(
        "admin/panel_reports.html",
        active="reports",
        reports=rows,
        counts=counts,
        status=status,
        pager=pager,
        content_types=CONTENT,
    )


@panel_bp.post("/admin/reports/<int:report_id>/resolve")
@admin_required
@csrf_protected
def report_resolve(report_id):
    action = request.form.get("action", "")
    back = safe_next(request.form.get("next")) or url_for("panel.reports_page")

    if action not in ("dismiss", "hide", "block_author"):
        flash("Kitendo si sahihi.", "error")
        return redirect(back)

    resolution = {
        "dismiss": "dismissed",
        "hide": "content_hidden",
        "block_author": "author_blocked",
    }[action]

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT content_type, content_id, status FROM content_reports WHERE id = %s",
                (report_id,),
            )
            row = cursor.fetchone()

            if not row:
                flash("Report haijapatikana.", "error")
                return redirect(back)

            ctype, content_id, current = row

            if current != "open":
                flash("Report hii tayari imeshughulikiwa.", "error")
                return redirect(back)

            blocked_user = None

            if action in ("hide", "block_author") and ctype in CONTENT:
                table = CONTENT[ctype]["table"]

                cursor.execute(
                    f"SELECT user_id FROM {table} WHERE id = %s", (content_id,)
                )
                content_row = cursor.fetchone()

                cursor.execute(
                    f"UPDATE {table} SET status = 'hidden' WHERE id = %s", (content_id,)
                )

                if action == "block_author" and content_row and content_row[0]:
                    cursor.execute(
                        "UPDATE users SET status = 'blocked' "
                        "WHERE id = %s AND status = 'active'",
                        (content_row[0],),
                    )
                    blocked_user = content_row[0]

            # Funga reports zote wazi za maudhui hayo hayo (si moja tu)
            if action == "dismiss":
                cursor.execute(
                    """
                    UPDATE content_reports
                    SET status = 'resolved', resolution = %s, resolved_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (resolution, report_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE content_reports
                    SET status = 'resolved', resolution = %s, resolved_at = CURRENT_TIMESTAMP
                    WHERE content_type = %s AND content_id = %s AND status = 'open'
                    """,
                    (resolution, ctype, content_id),
                )

        if blocked_user:
            guard.invalidate(blocked_user)

        invalidate_badge()
        audit(f"report_{action}", ctype, content_id, f"report #{report_id}")

        flash(
            {
                "dismiss": "Report imekataliwa (hakuna ukiukaji).",
                "hide": "Maudhui yamefichwa na reports zake zimefungwa.",
                "block_author": "Maudhui yamefichwa na mwandishi amezuiwa.",
            }[action],
            "success",
        )

    except Exception as error:
        flash(f"Imeshindikana: {error}", "error")

    return redirect(back)


# ============================================================
# QUOTES HUB (ongeza moja, grid ya kuandika, CSV file)
# ============================================================

@panel_bp.get("/admin/quotes")
@admin_required
def quotes_page():
    tab = request.args.get("tab", "write")

    if tab not in ("write", "single", "csv"):
        tab = "write"

    categories = []
    recent = []
    total = 0

    try:
        with db_cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.name, c.slug,
                       (SELECT COUNT(*) FROM quotes q WHERE q.category_id = c.id)
                FROM categories c
                ORDER BY c.name ASC
                """
            )
            categories = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM quotes")
            total = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT q.id, q.text, q.author, c.name, q.language, q.created_at
                FROM quotes q
                LEFT JOIN categories c ON c.id = q.category_id
                ORDER BY q.id DESC
                LIMIT 12
                """
            )
            recent = cursor.fetchall()

    except Exception as error:
        flash(f"Imeshindikana kupakia quotes: {error}", "error")

    return render_template(
        "admin/panel_quotes.html",
        active="quotes",
        tab=tab,
        categories=categories,
        recent=recent,
        total=total,
        max_rows=MAX_IMPORT_ROWS,
    )


@panel_bp.get("/admin/quotes/template.csv")
@admin_required
def quotes_template_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["text", "author", "category", "language"])
    writer.writerow(["Mafanikio huanza kwa hatua ya kwanza", "Dutoza", "Motivation", "sw"])
    writer.writerow(["Never stop learning", "Dutoza", "Life", "en"])

    return Response(
        "\ufeff" + buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=quotes_template.csv"},
    )


LANGUAGE_ALIASES = {
    "sw": "sw", "swahili": "sw", "kiswahili": "sw",
    "en": "en", "english": "en", "kiingereza": "en",
}


@panel_bp.post("/admin/quotes/write/import")
@admin_required
@csrf_protected
def quotes_write_import():
    """
    Pokea rows zilizoandikwa kwenye grid (JSON) na uziingize kama quotes.
    Mantiki ni ile ile ya CSV upload: category huundwa kama haipo,
    duplicates zinarukwa (ON CONFLICT DO NOTHING).
    """
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")

    if not isinstance(rows, list) or not rows:
        return jsonify({"ok": False, "error": "Hakuna rows za kuingiza."}), 400

    if len(rows) > MAX_IMPORT_ROWS:
        return jsonify({
            "ok": False,
            "error": f"Rows nyingi mno. Kikomo ni {MAX_IMPORT_ROWS} kwa wakati mmoja.",
        }), 400

    total = len(rows)
    invalid = []
    batch = []
    categories_created = 0

    try:
        with db_cursor(commit=True) as cursor:
            cache = {}

            cursor.execute("SELECT id, name, slug FROM categories")

            for cid, name, slug in cursor.fetchall():
                if name:
                    cache[name.strip().lower()] = cid
                if slug:
                    cache[slug.strip().lower()] = cid

            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    invalid.append({"row": index, "reason": "Muundo si sahihi"})
                    continue

                number = row.get("n") or index
                text = str(row.get("text") or "").strip()
                author = str(row.get("author") or "").strip()
                category = str(row.get("category") or "").strip()
                language = LANGUAGE_ALIASES.get(
                    str(row.get("language") or "sw").strip().lower(), "sw"
                )

                if not text:
                    invalid.append({"row": number, "reason": "text haipo"})
                    continue

                if len(text) > MAX_QUOTE_LENGTH:
                    invalid.append({"row": number, "reason": f"text ndefu mno (>{MAX_QUOTE_LENGTH})"})
                    continue

                if not category:
                    invalid.append({"row": number, "reason": "category haipo"})
                    continue

                key = category.lower()
                category_id = cache.get(key)

                if category_id is None:
                    slug = slugify(category)

                    if not slug:
                        invalid.append({"row": number, "reason": "category si sahihi"})
                        continue

                    cursor.execute(
                        """
                        INSERT INTO categories (name, slug)
                        VALUES (%s, %s)
                        ON CONFLICT (slug) DO NOTHING
                        RETURNING id
                        """,
                        (category, slug),
                    )
                    created = cursor.fetchone()

                    if created:
                        category_id = created[0]
                        categories_created += 1
                    else:
                        cursor.execute("SELECT id FROM categories WHERE slug = %s", (slug,))
                        found = cursor.fetchone()

                        if not found:
                            invalid.append({"row": number, "reason": "category haikuundwa"})
                            continue

                        category_id = found[0]

                    cache[key] = category_id
                    cache[slug] = category_id

                batch.append((text, author or None, category_id, language))

            imported = 0

            if batch:
                cursor.executemany(
                    """
                    INSERT INTO quotes (text, author, category_id, language, status)
                    VALUES (%s, %s, %s, %s, 'published')
                    ON CONFLICT DO NOTHING
                    """,
                    batch,
                )
                imported = cursor.rowcount

                if imported is None or imported < 0:
                    imported = 0

        skipped = len(batch) - imported

        audit(
            "quotes_import",
            "quote",
            None,
            f"rows={total} imported={imported} skipped={skipped} invalid={len(invalid)}",
        )

        return jsonify({
            "ok": True,
            "total": total,
            "imported": imported,
            "skipped": skipped,
            "invalid": len(invalid),
            "invalid_rows": invalid[:50],
            "categories_created": categories_created,
        })

    except Exception as error:
        return jsonify({"ok": False, "error": f"Imeshindikana kuingiza: {error}"}), 500


# ============================================================
# DEVELOPERS (usimamizi wa developers na API keys zao)
# ============================================================

DEV_STATUSES = ["all", "active", "suspended"]
KEY_RATE_MIN = 1
KEY_RATE_MAX = 100000


@panel_bp.get("/admin/developers")
@admin_required
def developers_page():
    status = request.args.get("status", "all")
    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)

    if status not in DEV_STATUSES:
        status = "all"

    where = []
    params = []

    if status != "all":
        where.append("d.status = %s")
        params.append(status)

    if search:
        pattern = like_param(search)
        where.append(
            "(LOWER(d.name) LIKE %s ESCAPE '\\' OR LOWER(d.email) LIKE %s ESCAPE '\\')"
        )
        params.extend([pattern, pattern])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = []
    counts = {}
    totals = {"keys": 0, "requests": 0, "orphans": 0}
    pager = paginate(0, 1)

    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) FROM developers GROUP BY status")
            counts = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*), COALESCE(SUM(request_count), 0) FROM api_keys")
            keys_total, requests_total = cursor.fetchone()
            totals["keys"] = keys_total or 0
            totals["requests"] = requests_total or 0

            cursor.execute(
                """
                SELECT COUNT(*) FROM api_keys k
                WHERE NOT EXISTS (
                    SELECT 1 FROM developers d WHERE d.email = k.owner_email
                )
                """
            )
            totals["orphans"] = cursor.fetchone()[0] or 0

            cursor.execute(f"SELECT COUNT(*) FROM developers d {where_sql}", params)
            pager = paginate(cursor.fetchone()[0], page)

            cursor.execute(
                f"""
                SELECT
                    d.id, d.name, d.email, d.created_at, d.status,
                    (SELECT COUNT(*) FROM api_keys k WHERE k.owner_email = d.email),
                    (SELECT COUNT(*) FROM api_keys k
                      WHERE k.owner_email = d.email AND k.status = 'active'),
                    (SELECT COALESCE(SUM(k.request_count), 0) FROM api_keys k
                      WHERE k.owner_email = d.email),
                    (SELECT MAX(k.last_used_at) FROM api_keys k
                      WHERE k.owner_email = d.email)
                FROM developers d
                {where_sql}
                ORDER BY d.created_at DESC, d.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [pager["per_page"], pager["offset"]],
            )
            rows = cursor.fetchall()

    except Exception as error:
        flash(
            f"Imeshindikana kupakia developers: {error}. "
            "Fungua Schema Status na uendeshe schema upya.",
            "error",
        )

    counts["all"] = sum(counts.values())

    return render_template(
        "admin/panel_developers.html",
        active="developers",
        developers=rows,
        counts=counts,
        totals=totals,
        statuses=DEV_STATUSES,
        status=status,
        search=search,
        pager=pager,
    )


@panel_bp.get("/admin/developers/<int:dev_id>")
@admin_required
def developer_detail(dev_id):
    developer = None
    keys = []

    try:
        with db_cursor() as cursor:
            cursor.execute(
                "SELECT id, name, email, created_at, status FROM developers WHERE id = %s",
                (dev_id,),
            )
            developer = cursor.fetchone()

            if developer:
                cursor.execute(
                    """
                    SELECT id, name, key_prefix, status, rate_limit,
                           request_count, last_used_at, created_at
                    FROM api_keys
                    WHERE owner_email = %s
                    ORDER BY id DESC
                    """,
                    (developer[2],),
                )
                keys = cursor.fetchall()

    except Exception as error:
        flash(f"Imeshindikana kupakia developer: {error}", "error")
        return redirect(url_for("panel.developers_page"))

    if not developer:
        flash("Developer hajapatikana.", "error")
        return redirect(url_for("panel.developers_page"))

    active_keys = sum(1 for k in keys if k[3] == "active")
    total_requests = sum((k[5] or 0) for k in keys)
    last_used = max([k[6] for k in keys if k[6]], default=None, key=lambda v: str(v))

    return render_template(
        "admin/panel_developer.html",
        active="developers",
        dev=developer,
        keys=keys,
        active_keys=active_keys,
        total_requests=total_requests,
        last_used=last_used,
        rate_min=KEY_RATE_MIN,
        rate_max=KEY_RATE_MAX,
    )


@panel_bp.post("/admin/developers/<int:dev_id>/status")
@admin_required
@csrf_protected
def developer_set_status(dev_id):
    action = request.form.get("action", "")
    back = safe_next(request.form.get("next")) or url_for("panel.developer_detail", dev_id=dev_id)

    if action not in ("suspend", "reactivate"):
        flash("Kitendo si sahihi.", "error")
        return redirect(back)

    disabled_keys = 0

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT name, email, status FROM developers WHERE id = %s", (dev_id,)
            )
            row = cursor.fetchone()

            if not row:
                flash("Developer hajapatikana.", "error")
                return redirect(url_for("panel.developers_page"))

            name, email, current = row

            if action == "suspend":
                if current != "active":
                    flash(f"{name} ana status '{current}', kitendo hakiwezekani.", "error")
                    return redirect(back)

                cursor.execute(
                    "UPDATE developers SET status = 'suspended' WHERE id = %s", (dev_id,)
                )
                # Zima API keys zake zote zinazofanya kazi (zinaweza kuwashwa tena moja moja)
                cursor.execute(
                    "UPDATE api_keys SET status = 'inactive' "
                    "WHERE owner_email = %s AND status = 'active'",
                    (email,),
                )
                disabled_keys = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

            else:
                if current != "suspended":
                    flash(f"{name} ana status '{current}', kitendo hakiwezekani.", "error")
                    return redirect(back)

                cursor.execute(
                    "UPDATE developers SET status = 'active' WHERE id = %s", (dev_id,)
                )

        guard.invalidate_developer(dev_id)

        if action == "suspend":
            audit("developer_suspend", "developer", dev_id, f"{email}, keys zilizozimwa: {disabled_keys}")
            flash(
                f"{name} amesimamishwa. API keys {disabled_keys} zimezimwa na ametolewa kwenye dashboard yake.",
                "success",
            )
        else:
            audit("developer_reactivate", "developer", dev_id, email)
            flash(
                f"{name} amerudishwa. API keys zake bado zimezimwa; washa kila moja ukipenda.",
                "success",
            )

    except Exception as error:
        flash(
            f"Imeshindikana: {error}. "
            "Fungua Schema Status ili kuhakikisha column ya 'status' ya developers ipo.",
            "error",
        )

    return redirect(back)


@panel_bp.post("/admin/developers/keys/<int:key_id>/action")
@admin_required
@csrf_protected
def developer_key_action(key_id):
    action = request.form.get("action", "")
    back = safe_next(request.form.get("next")) or url_for("panel.developers_page")

    if action not in ("enable", "disable", "revoke"):
        flash("Kitendo si sahihi.", "error")
        return redirect(back)

    new_status = {"enable": "active", "disable": "inactive", "revoke": "revoked"}[action]

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                SELECT k.status, k.name, d.status
                FROM api_keys k
                LEFT JOIN developers d ON d.email = k.owner_email
                WHERE k.id = %s
                """,
                (key_id,),
            )
            row = cursor.fetchone()

            if not row:
                flash("API key haijapatikana.", "error")
                return redirect(back)

            current, key_name, dev_status = row

            if action == "enable":
                if current != "inactive":
                    flash(
                        "Key iliyofutwa (revoked) haiwezi kuwashwa tena."
                        if current == "revoked" else "Key tayari inafanya kazi.",
                        "error",
                    )
                    return redirect(back)

                if dev_status == "suspended":
                    flash("Developer amesimamishwa. Mrudishe kwanza kabla ya kuwasha key zake.", "error")
                    return redirect(back)

            elif action == "disable" and current != "active":
                flash("Key hii haifanyi kazi tayari.", "error")
                return redirect(back)

            elif action == "revoke" and current == "revoked":
                flash("Key hii tayari imefutwa.", "error")
                return redirect(back)

            cursor.execute(
                "UPDATE api_keys SET status = %s WHERE id = %s", (new_status, key_id)
            )

        audit(f"key_{action}", "api_key", key_id, key_name)
        flash(
            {
                "enable": "Key imewashwa.",
                "disable": "Key imezimwa.",
                "revoke": "Key imefutwa kabisa (haiwezi kurudishwa).",
            }[action],
            "success",
        )

    except Exception as error:
        flash(f"Imeshindikana: {error}", "error")

    return redirect(back)


@panel_bp.post("/admin/developers/keys/<int:key_id>/limit")
@admin_required
@csrf_protected
def developer_key_limit(key_id):
    back = safe_next(request.form.get("next")) or url_for("panel.developers_page")
    limit = request.form.get("rate_limit", type=int)

    if limit is None or limit < KEY_RATE_MIN or limit > KEY_RATE_MAX:
        flash(f"Limit lazima iwe kati ya {KEY_RATE_MIN} na {KEY_RATE_MAX} kwa dakika.", "error")
        return redirect(back)

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE api_keys SET rate_limit = %s WHERE id = %s", (limit, key_id)
            )

            if cursor.rowcount == 0:
                flash("API key haijapatikana.", "error")
                return redirect(back)

        audit("key_limit", "api_key", key_id, f"{limit}/dakika")
        flash(f"Limit imewekwa kuwa {limit} requests kwa dakika.", "success")

    except Exception as error:
        flash(f"Imeshindikana: {error}", "error")

    return redirect(back)
