"""
Developer portal: akaunti za developers, API keys, profile na settings.

Docs za umma ziko kwenye /developers (templates/developers/index.html);
kurasa za ndani (dashboard, keys, profile, settings) zinahitaji kuingia.

Mpangilio wa faili:
  1. Mipangilio na orodha za thamani
  2. Vifaa: CSRF, decorator ya login, kusoma data (rows zenye majina)
  3. Docs na login/register
  4. Kurasa za portal: dashboard, keys, profile, settings
  5. API keys: tengeneza na futa
"""

import logging
import re
import secrets
from functools import wraps

from flask import (
    Blueprint,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import throttle
from auth import generate_api_key, hash_api_key
from db import db_cursor
from schema import ensure_schema

log = logging.getLogger("mercfy.developers")

developers_bp = Blueprint("developers", __name__)


# ============================================================
# 1. MIPANGILIO
# ============================================================

# Huduma ambazo key inaweza kuomba -> scopes zinazohifadhiwa
SERVICE_CHOICES = {
    "quotes": "quotes",
    "music": "music",
    "all": "quotes,music",
}
SERVICE_LABELS = {
    "quotes": "Quotes",
    "music": "Music",
    "quotes,music": "Quotes + Music",
}

STATUS_LABELS = {
    "active": "ACTIVE",
    "pending": "PENDING APPROVAL",
    "rejected": "REJECTED",
    "revoked": "REVOKED",
    "inactive": "DISABLED",
}
STATUS_CLASSES = {
    "rejected": "revoked",
    "revoked": "revoked",
    "pending": "pending",
    "inactive": "inactive",
}

PROJECT_TYPES = ("mobile", "website", "backend", "learning")
USAGE_CHOICES = ("", "low", "medium", "high")

PROFILE_LIMITS = {
    "name": (2, 100),
    "company": (0, 150),
    "website": (0, 255),
    "country": (0, 80),
    "bio": (0, 300),
}

EMAIL_MAX = 255
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8
PASSWORD_MAX = 128   # nenosiri refu sana linafanya hashing kuwa nzito bila sababu

REGISTER_LIMIT = 5   # akaunti mpya kwa dakika 10 kwa kila IP
LOGIN_LIMIT = 8      # majaribio yasiyofaa kwa dakika 10 kwa kila IP

PURPOSE_MIN = 10
PURPOSE_MAX = 500
MAX_PENDING_PER_DEVELOPER = 3
DEFAULT_RATE_LIMIT = 100
KEY_PREFIX_LENGTH = 15

# Columns zinazosomwa (SELECT inajengwa kutoka hapa: majina ni ya ndani, si ya mtumiaji)
DEVELOPER_COLUMNS = (
    "id", "name", "email", "created_at", "status",
    "company", "website", "country", "bio",
)
KEY_COLUMNS = (
    "id", "name", "key_prefix", "status", "last_used_at", "created_at",
    "request_count", "rate_limit", "scopes", "review_note",
)


# ============================================================
# 2. VIFAA
# ============================================================

def dev_csrf():
    """CSRF token ya fomu za profile na settings."""
    token = session.get("dev_csrf")

    if not token:
        token = secrets.token_urlsafe(32)
        session["dev_csrf"] = token

    return token


def dev_csrf_ok():
    sent = request.form.get("csrf_token") or ""
    expected = session.get("dev_csrf") or ""

    return bool(expected) and secrets.compare_digest(sent, expected)


def developer_required(view):
    """Njia ya ndani: lazima awe ameingia. Id yake inapatikana kama g.developer_id."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        developer_id = session.get("developer_id")

        if not developer_id:
            return redirect(url_for("developers.login"))

        g.developer_id = developer_id

        return view(*args, **kwargs)

    return wrapped


def sign_out_missing_developer():
    """Akaunti haipo tena (imefutwa): futa session na rudi kwenye login."""
    session.clear()
    return redirect(url_for("developers.login"))


def fetch_all(cursor, sql, params, columns):
    """Endesha query na rudisha rows kama dict zenye majina ya columns."""
    cursor.execute(sql, params)
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_developer(cursor, developer_id):
    rows = fetch_all(
        cursor,
        "SELECT " + ", ".join(DEVELOPER_COLUMNS) + " FROM developers WHERE id = %s",
        (developer_id,),
        DEVELOPER_COLUMNS,
    )

    return rows[0] if rows else None


def load_keys(cursor, email):
    """API keys za developer, tayari na maandishi ya kuonyesha (service, status)."""
    keys = fetch_all(
        cursor,
        "SELECT " + ", ".join(KEY_COLUMNS)
        + " FROM api_keys WHERE owner_email = %s ORDER BY created_at DESC",
        (email,),
        KEY_COLUMNS,
    )

    for key in keys:
        key["request_count"] = key["request_count"] or 0
        key["rate_limit"] = key["rate_limit"] or DEFAULT_RATE_LIMIT
        key["service"] = SERVICE_LABELS.get(key["scopes"], "Quotes")
        key["status_label"] = STATUS_LABELS.get(key["status"], str(key["status"]).upper())
        key["status_class"] = STATUS_CLASSES.get(key["status"], "")

    return keys


def key_stats(keys):
    used = [key["last_used_at"] for key in keys if key["last_used_at"]]

    return {
        "total": len(keys),
        "active": sum(1 for key in keys if key["status"] == "active"),
        "pending": sum(1 for key in keys if key["status"] == "pending"),
        "requests": sum(key["request_count"] for key in keys),
        "last_used": max(used, default=None),
    }


@developers_bp.before_request
def prepare_schema():
    """Tables zikiwa hazijakamilika wakati app inaanza, zinajaribiwa hapa (ni rahisi baada ya mara ya kwanza)."""
    if request.endpoint != "developers.docs":
        ensure_schema()


# ============================================================
# 3. DOCS, LOGIN, REGISTER
# ============================================================

@developers_bp.get("/developers")
def docs():
    return render_template(
        "developers/index.html",
        developer_logged_in=bool(session.get("developer_id")),
        nav_active="docs",
    )


@developers_bp.get("/developers/login")
def login():
    if session.get("developer_id"):
        return redirect(url_for("developers.dashboard"))

    return render_template("developers/login.html")


@developers_bp.post("/developers/login")
def login_post():
    wait = throttle.seconds_locked("developer", LOGIN_LIMIT)

    if wait:
        flash(
            "Umejaribu mara nyingi mno. Subiri dakika "
            + str(throttle.minutes_text(wait))
            + " kisha ujaribu tena."
        )
        return redirect(url_for("developers.login"))

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Weka email na password.")
        return redirect(url_for("developers.login"))

    with db_cursor() as cursor:
        cursor.execute(
            "SELECT id, password_hash, status FROM developers WHERE email = %s",
            (email,),
        )
        developer = cursor.fetchone()

    if not developer or not check_password_hash(developer[1], password):
        throttle.record_failure("developer")
        flash("Email au password si sahihi.")
        return redirect(url_for("developers.login"))

    throttle.clear("developer")

    if developer[2] == "suspended":
        flash("Akaunti yako ya developer imesimamishwa. Wasiliana na admin.")
        return redirect(url_for("developers.login"))

    session.clear()
    session["developer_id"] = developer[0]

    return redirect(url_for("developers.dashboard"))


@developers_bp.get("/developers/register")
def register():
    if session.get("developer_id"):
        return redirect(url_for("developers.dashboard"))

    return render_template("developers/register.html")


def registration_error(name, email, password):
    """Ujumbe wa kosa la fomu ya kujisajili, au None kama kila kitu kiko sawa."""
    name_min, name_max = PROFILE_LIMITS["name"]

    if not name or not email or not password:
        return "Jaza sehemu zote."

    if not name_min <= len(name) <= name_max:
        return "Jina liwe na herufi %d hadi %d." % (name_min, name_max)

    if len(email) > EMAIL_MAX or not EMAIL_PATTERN.match(email):
        return "Weka email sahihi."

    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return "Password iwe na herufi %d hadi %d." % (PASSWORD_MIN, PASSWORD_MAX)

    return None


@developers_bp.post("/developers/register")
def register_post():
    if throttle.seconds_locked("developer_register", REGISTER_LIMIT):
        flash("Umejaribu kujisajili mara nyingi mno. Jaribu tena baadaye.")
        return redirect(url_for("developers.register"))

    throttle.record_failure("developer_register")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = registration_error(name, email, password)

    if error:
        flash(error)
        return redirect(url_for("developers.register"))

    # Query moja: ON CONFLICT inashughulikia pia mbio la wawili wenye email moja
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO developers (name, email, password_hash)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            RETURNING id
            """,
            (name, email, generate_password_hash(password)),
        )
        created = cursor.fetchone()

    if not created:
        flash("Tayari kuna akaunti yenye email hii.")
        return redirect(url_for("developers.login"))

    # Hapati API key moja kwa moja: anatengeneza mwenyewe kwenye dashboard.
    session.clear()
    session["developer_id"] = created[0]

    flash(
        "Akaunti imefunguliwa. Tengeneza API key yako ya kwanza hapa chini "
        "ili uanze kutumia API."
    )

    return redirect(url_for("developers.dashboard"))


@developers_bp.post("/developers/logout")
def logout():
    session.clear()
    return redirect(url_for("developers.login"))


# ============================================================
# 4. KURASA ZA PORTAL
# ============================================================

@developers_bp.get("/developers/dashboard")
@developer_required
def dashboard():
    with db_cursor() as cursor:
        developer = load_developer(cursor, g.developer_id)

        if not developer:
            return sign_out_missing_developer()

        keys = load_keys(cursor, developer["email"])

    return render_template(
        "developers/dashboard.html",
        developer=developer,
        api_keys=keys,
        stats=key_stats(keys),
        nav_active="dashboard",
    )


@developers_bp.get("/developers/keys")
@developer_required
def keys_page():
    with db_cursor() as cursor:
        developer = load_developer(cursor, g.developer_id)

        if not developer:
            return sign_out_missing_developer()

        keys = load_keys(cursor, developer["email"])

    return render_template(
        "developers/keys.html",
        developer=developer,
        api_keys=keys,
        stats=key_stats(keys),
        # Key kamili inaonyeshwa mara moja tu, mara baada ya kutengenezwa
        new_api_key=session.pop("new_api_key", None),
        nav_active="keys",
    )


def render_profile(developer, keys, form=None, error=None, status=200):
    values = form or {
        field: developer[field] or "" for field in PROFILE_LIMITS
    }

    return make_response(render_template(
        "developers/profile.html",
        developer=developer,
        stats=key_stats(keys),
        form=values,
        error=error,
        csrf_token=dev_csrf(),
        limits=PROFILE_LIMITS,
        nav_active="profile",
    ), status)


@developers_bp.get("/developers/profile")
@developer_required
def profile():
    with db_cursor() as cursor:
        developer = load_developer(cursor, g.developer_id)

        if not developer:
            return sign_out_missing_developer()

        keys = load_keys(cursor, developer["email"])

    return render_profile(developer, keys)


def profile_error(form):
    """Kosa la kwanza kwenye fomu ya profile, au None."""
    for field, (minimum, maximum) in PROFILE_LIMITS.items():
        length = len(form[field])

        if minimum <= length <= maximum:
            continue

        label = field.capitalize()

        if minimum and length == 0:
            return f"{label} is required."

        if minimum:
            return f"{label} must be between {minimum} and {maximum} characters."

        return f"{label} must be at most {maximum} characters."

    website = form["website"]

    if website and not website.lower().startswith(("http://", "https://")):
        return "Website must start with http:// or https://"

    return None


@developers_bp.post("/developers/profile")
@developer_required
def profile_post():
    form = {field: (request.form.get(field) or "").strip() for field in PROFILE_LIMITS}

    with db_cursor(commit=True) as cursor:
        developer = load_developer(cursor, g.developer_id)

        if not developer:
            return sign_out_missing_developer()

        keys = load_keys(cursor, developer["email"])

        if not dev_csrf_ok():
            return render_profile(
                developer, keys, form, "Your session expired. Please try again.", 400
            )

        error = profile_error(form)

        if error:
            return render_profile(developer, keys, form, error, 400)

        try:
            cursor.execute(
                """
                UPDATE developers
                SET name = %s, company = %s, website = %s, country = %s, bio = %s
                WHERE id = %s
                """,
                (
                    form["name"],
                    form["company"] or None,
                    form["website"] or None,
                    form["country"] or None,
                    form["bio"] or None,
                    developer["id"],
                ),
            )

            # Jina linaonekana pia kwenye keys zake
            cursor.execute(
                "UPDATE api_keys SET owner_name = %s WHERE owner_email = %s",
                (form["name"], developer["email"]),
            )

        except Exception:
            cursor.connection.rollback()
            log.exception("Imeshindwa kusasisha profile ya developer %s", developer["id"])

            return render_profile(
                developer, keys, form,
                "We could not save your profile right now. "
                "Please try again later or contact support.", 500,
            )

    flash("Profile updated.", "success")

    return redirect(url_for("developers.profile"))


def render_settings(developer, error=None, status=200):
    return make_response(render_template(
        "developers/settings.html",
        developer=developer,
        csrf_token=dev_csrf(),
        password_min=PASSWORD_MIN,
        error=error,
        nav_active="settings",
    ), status)


@developers_bp.get("/developers/settings")
@developer_required
def settings():
    with db_cursor() as cursor:
        developer = load_developer(cursor, g.developer_id)

    if not developer:
        return sign_out_missing_developer()

    return render_settings(developer)


def password_change_error(password_hash, current, new, confirm):
    """Kosa la kubadili password, au None."""
    if not dev_csrf_ok():
        return "Your session expired. Please try again."

    if not current or not new or not confirm:
        return "Please fill in all password fields."

    if not check_password_hash(password_hash, current):
        return "Your current password is incorrect."

    if not PASSWORD_MIN <= len(new) <= PASSWORD_MAX:
        return f"New password must be between {PASSWORD_MIN} and {PASSWORD_MAX} characters."

    if new != confirm:
        return "New password and confirmation do not match."

    if new == current:
        return "New password must be different from your current password."

    return None


@developers_bp.post("/developers/settings/password")
@developer_required
def change_password():
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    with db_cursor(commit=True) as cursor:
        developer = load_developer(cursor, g.developer_id)

        if not developer:
            return sign_out_missing_developer()

        cursor.execute(
            "SELECT password_hash FROM developers WHERE id = %s",
            (developer["id"],),
        )
        password_hash = cursor.fetchone()[0]

        error = password_change_error(password_hash, current, new, confirm)

        if error:
            return render_settings(developer, error, 400)

        cursor.execute(
            "UPDATE developers SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new), developer["id"]),
        )

    flash("Password updated.", "success")

    return redirect(url_for("developers.settings"))


# ============================================================
# 5. API KEYS
# ============================================================

@developers_bp.post("/developers/api-keys/<int:key_id>/revoke")
@developer_required
def revoke_api_key(key_id):
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE api_keys
                SET status = 'revoked'
                WHERE id = %s
                  AND owner_email = (SELECT email FROM developers WHERE id = %s)
                  AND status IN ('active', 'pending')
                """,
                (key_id, g.developer_id),
            )
            changed = cursor.rowcount

    except Exception:
        log.exception("Imeshindwa kufuta key %s", key_id)
        flash("We could not revoke the key right now. Please try again.", "error")
        return redirect(url_for("developers.keys_page"))

    if changed:
        flash("API key revoked.", "success")
    else:
        flash("This key was not found or is already inactive.", "error")

    return redirect(url_for("developers.keys_page"))


def key_request_error(form):
    """(kosa, thamani zilizosafishwa). Kosa ni None kama fomu iko sawa."""
    values = {
        "name": (form.get("name", "").strip() or "Developer API Key")[:150],
        "service": form.get("service", ""),
        "purpose": form.get("purpose", "").strip(),
        "project_type": form.get("project_type", ""),
        "website": form.get("website", "").strip(),
        "expected_usage": form.get("expected_usage", ""),
    }
    website = values["website"]

    if values["service"] not in SERVICE_CHOICES:
        error = "Please choose which service the key is for."
    elif not PURPOSE_MIN <= len(values["purpose"]) <= PURPOSE_MAX:
        error = (
            "Please describe how you will use the API "
            f"({PURPOSE_MIN}-{PURPOSE_MAX} characters)."
        )
    elif values["project_type"] not in PROJECT_TYPES:
        error = "Please choose a project type."
    elif values["expected_usage"] not in USAGE_CHOICES:
        error = "Invalid expected usage."
    elif website and (
        len(website) > 255 or not website.lower().startswith(("http://", "https://"))
    ):
        error = "Website must start with http:// or https:// (max 255 characters)."
    elif form.get("accept_terms") != "yes":
        error = "You must accept the terms of use to create a key."
    else:
        error = None

    return error, values


@developers_bp.post("/developers/api-keys/create")
@developer_required
def create_api_key():
    error, values = key_request_error(request.form)

    if error:
        flash(error, "error")
        return redirect(url_for("developers.keys_page"))

    scopes = SERVICE_CHOICES[values["service"]]

    # Quotes pekee inaanza kufanya kazi mara moja.
    # Muziki (au Zote) inasubiri idhini ya admin.
    status = "active" if scopes == "quotes" else "pending"

    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT name, email FROM developers WHERE id = %s",
                (g.developer_id,),
            )
            developer = cursor.fetchone()

            if not developer:
                return sign_out_missing_developer()

            if status == "pending":
                cursor.execute(
                    "SELECT COUNT(*) FROM api_keys WHERE owner_email = %s AND status = 'pending'",
                    (developer[1],),
                )

                if cursor.fetchone()[0] >= MAX_PENDING_PER_DEVELOPER:
                    flash(
                        f"You already have {MAX_PENDING_PER_DEVELOPER} requests "
                        "waiting for approval. Please wait for a decision first.",
                        "error",
                    )
                    return redirect(url_for("developers.keys_page"))

            api_key = generate_api_key()

            cursor.execute(
                """
                INSERT INTO api_keys (
                    name, key_hash, key_prefix, owner_name, owner_email,
                    status, rate_limit, scopes, purpose, project_type,
                    website, expected_usage, terms_accepted_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    values["name"],
                    hash_api_key(api_key),
                    api_key[:KEY_PREFIX_LENGTH],
                    developer[0],
                    developer[1],
                    status,
                    DEFAULT_RATE_LIMIT,
                    scopes,
                    values["purpose"],
                    values["project_type"],
                    values["website"] or None,
                    values["expected_usage"] or None,
                ),
            )

    except Exception:
        log.exception("Imeshindwa kutengeneza API key")
        flash(
            "We could not create the key right now. "
            "Please try again later or contact support.",
            "error",
        )
        return redirect(url_for("developers.keys_page"))

    session["new_api_key"] = api_key

    if status == "pending":
        flash(
            "Your request was submitted. Your key will start working "
            "once an administrator approves it. Save the key below now: "
            "it is shown only once."
        )

    return redirect(url_for("developers.keys_page"))
