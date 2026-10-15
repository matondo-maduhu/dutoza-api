from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_connection
from auth import generate_api_key, hash_api_key
from schema import ensure_schema
import throttle
import secrets
import traceback


developers_bp = Blueprint("developers", __name__)

# Huduma ambazo key inaweza kuomba -> scopes zinazohifadhiwa
SERVICE_CHOICES = {
    "quotes": "quotes",
    "music": "music",
    "all": "quotes,music",
}

PROJECT_TYPES = ("mobile", "website", "backend", "learning")
USAGE_CHOICES = ("", "low", "medium", "high")

PROFILE_LIMITS = {"name": (2, 100), "company": (0, 150), "website": (0, 255),
                  "country": (0, 80), "bio": (0, 300)}
PASSWORD_MIN = 8
REGISTER_LIMIT = 5         # akaunti mpya kwa dakika 10 kwa kila IP
LOGIN_LIMIT = 8            # majaribio yasiyofaa kwa dakika 10 kwa kila IP

PURPOSE_MIN = 10
PURPOSE_MAX = 500
MAX_PENDING_PER_DEVELOPER = 3


def ensure_developers_table():
    """Table sasa inatengenezwa mara moja (schema.py), si kila request."""
    ensure_schema()


def dev_csrf():
    """CSRF token ya fomu mpya za developer (profile na settings)."""
    token = session.get("dev_csrf")

    if not token:
        token = secrets.token_urlsafe(32)
        session["dev_csrf"] = token

    return token


def dev_csrf_ok():
    sent = request.form.get("csrf_token") or ""
    expected = session.get("dev_csrf") or ""

    return bool(expected) and secrets.compare_digest(sent, expected)


def load_keys(cursor, email):
    """API keys za developer (zenye fallback kama schema mpya haijaendeshwa)."""
    try:
        cursor.execute(
            """
            SELECT id, name, key_prefix, status, last_used_at, created_at,
                   request_count, rate_limit, scopes, review_note
            FROM api_keys
            WHERE owner_email = %s
            ORDER BY created_at DESC
            """,
            (email,)
        )

        return cursor.fetchall()

    except Exception:
        # Schema mpya haijaendeshwa bado - tumia query ya zamani
        cursor.connection.rollback()

        cursor.execute(
            """
            SELECT id, name, key_prefix, status, last_used_at, created_at,
                   request_count, rate_limit
            FROM api_keys
            WHERE owner_email = %s
            ORDER BY created_at DESC
            """,
            (email,)
        )

        return [
            tuple(row) + ("quotes,music", None)
            for row in cursor.fetchall()
        ]


def key_stats(api_keys):
    active = sum(1 for k in api_keys if k[3] == "active")
    pending = sum(1 for k in api_keys if k[3] == "pending")
    requests_total = sum((k[6] or 0) for k in api_keys)
    last_used = max(
        [k[4] for k in api_keys if k[4]],
        default=None,
        key=lambda value: str(value)
    )

    return {
        "total": len(api_keys),
        "active": active,
        "pending": pending,
        "requests": requests_total,
        "last_used": last_used,
    }


@developers_bp.get("/developers/login")
def login():
    ensure_developers_table()

    if session.get("developer_id"):
        return redirect(url_for("developers.dashboard"))

    return render_template("developers/login.html")


@developers_bp.post("/developers/login")
def login_post():
    ensure_developers_table()

    wait = throttle.seconds_locked("developer", LOGIN_LIMIT)

    if wait:
        flash(
            "Too many failed attempts. Please wait "
            + str(throttle.minutes_text(wait))
            + " minute(s) and try again.",
            "error"
        )
        return redirect(url_for("developers.login"))

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.")
        return redirect(url_for("developers.login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, password_hash
            FROM developers
            WHERE email = %s
            """,
            (email,)
        )

        developer = cursor.fetchone()

        if not developer or not check_password_hash(
            developer[1],
            password
        ):
            throttle.record_failure("developer")
            flash("Invalid email or password.", "error")
            return redirect(url_for("developers.login"))

        throttle.clear("developer")
        session.clear()
        session["developer_id"] = developer[0]

        return redirect(url_for("developers.dashboard"))

    finally:
        if connection:
            connection.close()


@developers_bp.get("/developers/register")
def register():
    ensure_developers_table()

    if session.get("developer_id"):
        return redirect(url_for("developers.dashboard"))

    return render_template("developers/register.html")


@developers_bp.post("/developers/register")
def register_post():
    ensure_developers_table()

    if throttle.seconds_locked("developer_register", REGISTER_LIMIT):
        flash("Too many sign-up attempts. Please try again later.", "error")
        return redirect(url_for("developers.register"))

    throttle.record_failure("developer_register")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        flash("All fields are required.")
        return redirect(url_for("developers.register"))

    if len(password) < 8:
        flash("Password must contain at least 8 characters.")
        return redirect(url_for("developers.register"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM developers
            WHERE email = %s
            """,
            (email,)
        )

        if cursor.fetchone():
            flash("An account with this email already exists.")
            return redirect(url_for("developers.login"))

        cursor.execute(
            """
            INSERT INTO developers
                (name, email, password_hash)
            VALUES
                (%s, %s, %s)
            RETURNING id
            """,
            (
                name,
                email,
                generate_password_hash(password)
            )
        )

        developer_id = cursor.fetchone()[0]

        # Developer habadiliki kupewa API key moja kwa moja.
        # Anatengeneza mwenyewe kwenye dashboard (Create New API Key).
        connection.commit()

        session.clear()
        session["developer_id"] = developer_id

        flash(
            "Account created. Create your first API key below "
            "to start using the API."
        )

        return redirect(url_for("developers.dashboard"))

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if connection:
            connection.close()


def portal_context(cursor, developer_id):
    """(developer, api_keys) au None kama developer hayupo."""
    cursor.execute(
        """
        SELECT d.id, d.name, d.email, d.created_at
        FROM developers d
        WHERE d.id = %s
        """,
        (developer_id,)
    )

    developer = cursor.fetchone()

    if not developer:
        return None

    return developer, load_keys(cursor, developer[2])


@developers_bp.get("/developers/dashboard")
def dashboard():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        context = portal_context(cursor, developer_id)

        if not context:
            session.clear()
            return redirect(url_for("developers.login"))

        developer, api_keys = context

        return render_template(
            "developers/dashboard.html",
            developer=developer,
            api_keys=api_keys,
            stats=key_stats(api_keys),
            nav_active="dashboard"
        )

    finally:
        if connection:
            connection.close()


@developers_bp.get("/developers/keys")
def keys_page():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        context = portal_context(cursor, developer_id)

        if not context:
            session.clear()
            return redirect(url_for("developers.login"))

        developer, api_keys = context

        # Key kamili inaonyeshwa mara moja tu, mara baada ya kutengenezwa
        new_api_key = session.pop("new_api_key", None)

        return render_template(
            "developers/keys.html",
            developer=developer,
            api_keys=api_keys,
            stats=key_stats(api_keys),
            new_api_key=new_api_key,
            nav_active="keys"
        )

    finally:
        if connection:
            connection.close()


PROFILE_SELECT = """
    SELECT id, name, email, created_at, status, company, website, country, bio
    FROM developers
    WHERE id = %s
"""


def load_profile(cursor, developer_id):
    """Profile kamili; kama columns mpya hazipo bado, zinajazwa tupu."""
    try:
        cursor.execute(PROFILE_SELECT, (developer_id,))
        return cursor.fetchone()

    except Exception:
        cursor.connection.rollback()

        cursor.execute(
            "SELECT id, name, email, created_at FROM developers WHERE id = %s",
            (developer_id,)
        )

        row = cursor.fetchone()

        if not row:
            return None

        return tuple(row) + ("active", None, None, None, None)


def render_profile(developer, api_keys, form=None, error=None, status=200):
    from flask import make_response

    values = form or {
        "name": developer[1] or "",
        "company": developer[5] or "",
        "website": developer[6] or "",
        "country": developer[7] or "",
        "bio": developer[8] or "",
    }

    response = make_response(render_template(
        "developers/profile.html",
        developer=developer,
        profile=developer,
        stats=key_stats(api_keys),
        form=values,
        error=error,
        csrf_token=dev_csrf(),
        limits=PROFILE_LIMITS,
        nav_active="profile"
    ), status)

    return response


@developers_bp.get("/developers/profile")
def profile():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        developer = load_profile(cursor, developer_id)

        if not developer:
            session.clear()
            return redirect(url_for("developers.login"))

        return render_profile(developer, load_keys(cursor, developer[2]))

    finally:
        if connection:
            connection.close()


@developers_bp.post("/developers/profile")
def profile_post():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        developer = load_profile(cursor, developer_id)

        if not developer:
            session.clear()
            return redirect(url_for("developers.login"))

        api_keys = load_keys(cursor, developer[2])

        form = {
            field: (request.form.get(field) or "").strip()
            for field in PROFILE_LIMITS
        }

        if not dev_csrf_ok():
            return render_profile(
                developer, api_keys, form,
                "Your session expired. Please try again.", 400
            )

        error = None

        for field, (minimum, maximum) in PROFILE_LIMITS.items():
            length = len(form[field])

            if length < minimum or length > maximum:
                label = field.capitalize()

                error = (
                    f"{label} is required."
                    if minimum and length == 0 else
                    f"{label} must be between {minimum} and {maximum} characters."
                    if minimum else
                    f"{label} must be at most {maximum} characters."
                )
                break

        if not error and form["website"] and not form["website"].lower().startswith(
            ("http://", "https://")
        ):
            error = "Website must start with http:// or https://"

        if error:
            return render_profile(developer, api_keys, form, error, 400)

        try:
            cursor.execute(
                """
                UPDATE developers
                SET name = %s, company = %s, website = %s,
                    country = %s, bio = %s
                WHERE id = %s
                """,
                (
                    form["name"],
                    form["company"] or None,
                    form["website"] or None,
                    form["country"] or None,
                    form["bio"] or None,
                    developer_id
                )
            )

            # Jina linaonekana pia kwenye keys zake
            cursor.execute(
                "UPDATE api_keys SET owner_name = %s WHERE owner_email = %s",
                (form["name"], developer[2])
            )

            connection.commit()

        except Exception:
            connection.rollback()
            traceback.print_exc()

            return render_profile(
                developer, api_keys, form,
                "We could not save your profile right now. "
                "Please try again later or contact support.", 500
            )

        flash("Profile updated.", "success")

        return redirect(url_for("developers.profile"))

    finally:
        if connection:
            connection.close()


@developers_bp.get("/developers/settings")
def settings():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        context = portal_context(cursor, developer_id)

        if not context:
            session.clear()
            return redirect(url_for("developers.login"))

        return render_template(
            "developers/settings.html",
            developer=context[0],
            csrf_token=dev_csrf(),
            password_min=PASSWORD_MIN,
            error=None,
            nav_active="settings"
        )

    finally:
        if connection:
            connection.close()


@developers_bp.post("/developers/settings/password")
def change_password():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, name, email, created_at, password_hash
            FROM developers
            WHERE id = %s
            """,
            (developer_id,)
        )

        row = cursor.fetchone()

        if not row:
            session.clear()
            return redirect(url_for("developers.login"))

        error = None

        if not dev_csrf_ok():
            error = "Your session expired. Please try again."
        elif not current or not new or not confirm:
            error = "Please fill in all password fields."
        elif not check_password_hash(row[4], current):
            error = "Your current password is incorrect."
        elif len(new) < PASSWORD_MIN:
            error = f"New password must be at least {PASSWORD_MIN} characters."
        elif new != confirm:
            error = "New password and confirmation do not match."
        elif new == current:
            error = "New password must be different from your current password."

        if error:
            from flask import make_response

            return make_response(render_template(
                "developers/settings.html",
                developer=row[:4],
                csrf_token=dev_csrf(),
                password_min=PASSWORD_MIN,
                error=error,
                nav_active="settings"
            ), 400)

        cursor.execute(
            "UPDATE developers SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new), developer_id)
        )

        connection.commit()

        flash("Password updated.", "success")

        return redirect(url_for("developers.settings"))

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if connection:
            connection.close()


@developers_bp.post("/developers/logout")
def logout():
    session.clear()
    return redirect(url_for("developers.login"))

@developers_bp.post("/developers/api-keys/<int:key_id>/revoke")
def revoke_api_key(key_id):
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE api_keys
            SET status = 'revoked'
            WHERE id = %s
              AND owner_email = (
                  SELECT email
                  FROM developers
                  WHERE id = %s
              )
              AND status IN ('active', 'pending')
            """,
            (key_id, developer_id)
        )

        connection.commit()

        flash("API key revoked.", "success")

        return redirect(url_for("developers.keys_page"))

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if connection:
            connection.close()


@developers_bp.post("/developers/api-keys/create")
def create_api_key():
    developer_id = session.get("developer_id")

    if not developer_id:
        return redirect(url_for("developers.login"))

    ensure_developers_table()

    form = request.form

    key_name = form.get("name", "").strip() or "Developer API Key"
    key_name = key_name[:150]

    service = form.get("service", "")
    purpose = form.get("purpose", "").strip()
    project_type = form.get("project_type", "")
    website = form.get("website", "").strip()
    expected_usage = form.get("expected_usage", "")
    accepted_terms = form.get("accept_terms") == "yes"

    error = None

    if service not in SERVICE_CHOICES:
        error = "Please choose which service the key is for."
    elif not (PURPOSE_MIN <= len(purpose) <= PURPOSE_MAX):
        error = (
            f"Please describe how you will use the API "
            f"({PURPOSE_MIN}-{PURPOSE_MAX} characters)."
        )
    elif project_type not in PROJECT_TYPES:
        error = "Please choose a project type."
    elif expected_usage not in USAGE_CHOICES:
        error = "Invalid expected usage."
    elif website and (
        len(website) > 255
        or not website.lower().startswith(("http://", "https://"))
    ):
        error = "Website must start with http:// or https:// (max 255 characters)."
    elif not accepted_terms:
        error = "You must accept the terms of use to create a key."

    if error:
        flash(error, "error")
        return redirect(url_for("developers.keys_page"))

    scopes = SERVICE_CHOICES[service]

    # Quotes pekee inaanza kufanya kazi mara moja.
    # Muziki (au Zote) inasubiri idhini ya admin.
    status = "active" if scopes == "quotes" else "pending"

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT name, email
            FROM developers
            WHERE id = %s
            """,
            (developer_id,)
        )

        developer = cursor.fetchone()

        if not developer:
            session.clear()
            return redirect(url_for("developers.login"))

        if status == "pending":
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM api_keys
                WHERE owner_email = %s
                  AND status = 'pending'
                """,
                (developer[1],)
            )

            if cursor.fetchone()[0] >= MAX_PENDING_PER_DEVELOPER:
                flash(
                    f"You already have {MAX_PENDING_PER_DEVELOPER} requests "
                    "waiting for approval. Please wait for a decision first.",
                    "error"
                )
                return redirect(url_for("developers.keys_page"))

        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)

        cursor.execute(
            """
            INSERT INTO api_keys
                (
                    name,
                    key_hash,
                    key_prefix,
                    owner_name,
                    owner_email,
                    status,
                    rate_limit,
                    scopes,
                    purpose,
                    project_type,
                    website,
                    expected_usage,
                    terms_accepted_at
                )
            VALUES
                (
                    %s, %s, %s, %s, %s,
                    %s,
                    100,
                    %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP
                )
            """,
            (
                key_name,
                key_hash,
                api_key[:15],
                developer[0],
                developer[1],
                status,
                scopes,
                purpose,
                project_type,
                website or None,
                expected_usage or None
            )
        )

        connection.commit()

        session["new_api_key"] = api_key

        if status == "pending":
            flash(
                "Your request was submitted. Your key will start working "
                "once an administrator approves it. Save the key below now: "
                "it is shown only once."
            )

        return redirect(url_for("developers.keys_page"))

    except Exception:
        if connection:
            connection.rollback()

        traceback.print_exc()

        flash(
            "We could not create the key right now. "
            "Please try again later or contact support.",
            "error"
        )

        return redirect(url_for("developers.keys_page"))

    finally:
        if connection:
            connection.close()
