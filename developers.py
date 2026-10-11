from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_connection
from auth import generate_api_key, hash_api_key
from schema import ensure_schema
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

PURPOSE_MIN = 10
PURPOSE_MAX = 500
MAX_PENDING_PER_DEVELOPER = 3


def ensure_developers_table():
    """Table sasa inatengenezwa mara moja (schema.py), si kila request."""
    ensure_schema()


@developers_bp.get("/developers/login")
def login():
    ensure_developers_table()

    if session.get("developer_id"):
        return redirect(url_for("developers.dashboard"))

    return render_template("developers/login.html")


@developers_bp.post("/developers/login")
def login_post():
    ensure_developers_table()

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
            flash("Invalid email or password.")
            return redirect(url_for("developers.login"))

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

        cursor.execute(
            """
            SELECT
                d.id,
                d.name,
                d.email,
                d.created_at
            FROM developers d
            WHERE d.id = %s
            """,
            (developer_id,)
        )

        developer = cursor.fetchone()

        if not developer:
            session.clear()
            return redirect(url_for("developers.login"))

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    key_prefix,
                    status,
                    last_used_at,
                    created_at,
                    request_count,
                    rate_limit,
                    scopes,
                    review_note
                FROM api_keys
                WHERE owner_email = %s
                ORDER BY created_at DESC
                """,
                (developer[2],)
            )

            api_keys = cursor.fetchall()

        except Exception:
            # Schema mpya haijaendeshwa bado - tumia query ya zamani
            connection.rollback()

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    key_prefix,
                    status,
                    last_used_at,
                    created_at,
                    request_count,
                    rate_limit
                FROM api_keys
                WHERE owner_email = %s
                ORDER BY created_at DESC
                """,
                (developer[2],)
            )

            api_keys = [
                tuple(row) + ("quotes,music", None)
                for row in cursor.fetchall()
            ]

        new_api_key = session.pop("new_api_key", None)

        return render_template(
            "developers/dashboard.html",
            developer=developer,
            api_keys=api_keys,
            new_api_key=new_api_key
        )

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

        flash("API key imezimwa.")

        return redirect(url_for("developers.dashboard"))

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
        flash(error)
        return redirect(url_for("developers.dashboard"))

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
                    "waiting for approval. Please wait for a decision first."
                )
                return redirect(url_for("developers.dashboard"))

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

        return redirect(url_for("developers.dashboard"))

    except Exception:
        if connection:
            connection.rollback()

        traceback.print_exc()

        flash(
            "We could not create the key right now. "
            "Please try again later or contact support."
        )

        return redirect(url_for("developers.dashboard"))

    finally:
        if connection:
            connection.close()
