from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_connection


user_auth_bp = Blueprint("user_auth", __name__)


@user_auth_bp.get("/register")
def register():
    if session.get("user_id"):
        return redirect(url_for("user_feed.feed"))

    return render_template("users/register.html")


@user_auth_bp.post("/register")
def register_post():
    full_name = request.form.get("full_name", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not full_name or not username or not email or not password:
        flash("Jaza taarifa zote zinazohitajika.")
        return redirect(url_for("user_auth.register"))

    if len(full_name) < 2:
        flash("Jina kamili ni fupi sana.")
        return redirect(url_for("user_auth.register"))

    if len(username) < 3:
        flash("Username lazima iwe na angalau herufi 3.")
        return redirect(url_for("user_auth.register"))

    if len(username) > 50:
        flash("Username ni ndefu sana.")
        return redirect(url_for("user_auth.register"))

    if not password:
        flash("Password inahitajika.")
        return redirect(url_for("user_auth.register"))

    if len(password) < 8:
        flash("Password lazima iwe na angalau characters 8.")
        return redirect(url_for("user_auth.register"))

    if password != confirm_password:
        flash("Passwords hazifanani.")
        return redirect(url_for("user_auth.register"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE LOWER(username) = LOWER(%s)
               OR LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (username, email)
        )

        existing_user = cursor.fetchone()

        if existing_user:
            flash("Username au email tayari inatumika.")
            return redirect(url_for("user_auth.register"))

        cursor.execute(
            """
            INSERT INTO users (
                full_name,
                username,
                email,
                password_hash,
                status
            )
            VALUES (%s, %s, %s, %s, 'active')
            RETURNING id
            """,
            (
                full_name,
                username,
                email,
                generate_password_hash(password)
            )
        )

        user_id = cursor.fetchone()[0]

        connection.commit()

        session.clear()
        session["user_id"] = user_id

        return redirect(url_for("user_feed.feed"))

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if connection:
            connection.close()


@user_auth_bp.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("user_feed.feed"))

    return render_template("users/login.html")


@user_auth_bp.post("/login")
def login_post():
    email_or_username = request.form.get(
        "email_or_username",
        ""
    ).strip()

    password = request.form.get("password", "")

    if not email_or_username or not password:
        flash("Weka username/email na password.")
        return redirect(url_for("user_auth.login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                password_hash,
                status
            FROM users
            WHERE LOWER(email) = LOWER(%s)
               OR LOWER(username) = LOWER(%s)
            LIMIT 1
            """,
            (
                email_or_username,
                email_or_username
            )
        )

        user = cursor.fetchone()

        if not user:
            flash("Username/email au password si sahihi.")
            return redirect(url_for("user_auth.login"))

        user_id = user[0]
        password_hash = user[1]
        status = user[2]

        if status == "blocked":
            flash("Akaunti yako imezuiwa.")
            return redirect(url_for("user_auth.login"))

        if status == "deactivated":
            flash("Akaunti yako imezimwa.")
            return redirect(url_for("user_auth.login"))

        if not check_password_hash(
            password_hash,
            password
        ):
            flash("Username/email au password si sahihi.")
            return redirect(url_for("user_auth.login"))

        session.clear()
        session["user_id"] = user_id

        return redirect(url_for("user_feed.feed"))

    finally:
        if connection:
            connection.close()


@user_auth_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("user_auth.login"))


@user_auth_bp.get("/users/<username>")
def public_profile(username):
    current_user_id = session.get("user_id")

    if not current_user_id:
        return redirect(url_for("user_auth.login"))

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
                    full_name,
                    username,
                    email,
                    profile_image_url,
                    cover_image_url,
                    bio,
                    status,
                    created_at
                FROM users
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (username,)
            )

            user = cursor.fetchone()

            if not user or user[7] != "active":
                flash("Mtumiaji hakupatikana.")
                return redirect(url_for("user_feed.feed"))

            profile_user_id = user[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM subscriptions
                WHERE subscribed_to_id = %s
                """,
                (profile_user_id,)
            )
            subscribers_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM subscriptions
                WHERE subscriber_id = %s
                """,
                (profile_user_id,)
            )
            subscriptions_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM subscriptions
                    WHERE subscriber_id = %s
                      AND subscribed_to_id = %s
                )
                """,
                (current_user_id, profile_user_id)
            )
            is_subscribed = cursor.fetchone()[0]

            return render_template(
                "users/public_profile.html",
                user=user,
                subscribers_count=subscribers_count,
                subscriptions_count=subscriptions_count,
                is_subscribed=is_subscribed
            )

        except Exception as exc:
            if attempt == 0:
                error_name = type(exc).__name__

                if error_name in (
                    "InterfaceError",
                    "OperationalError",
                    "ConnectionError",
                ):
                    continue

            raise

        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

@user_auth_bp.post("/users/<int:user_id>/subscribe")
def subscribe_user(user_id):
    current_user_id = session.get("user_id")

    if not current_user_id:
        return redirect(url_for("user_auth.login"))

    if current_user_id == user_id:
        flash("Huwezi kujisubscribe mwenyewe.")
        return redirect(url_for("user_feed.feed"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, username, status
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,)
        )

        target_user = cursor.fetchone()

        if not target_user or target_user[2] != "active":
            flash("Mtumiaji hakupatikana.")
            return redirect(url_for("user_feed.feed"))

        cursor.execute(
            """
            INSERT INTO subscriptions (
                subscriber_id,
                subscribed_to_id
            )
            VALUES (%s, %s)
            ON CONFLICT (subscriber_id, subscribed_to_id)
            DO NOTHING
            RETURNING id
            """,
            (current_user_id, user_id)
        )

        new_subscription = cursor.fetchone()

        if new_subscription:
            subscription_id = new_subscription[0]

            cursor.execute(
                """
                SELECT full_name, username
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (current_user_id,)
            )

            actor = cursor.fetchone()

            actor_name = actor[0] if actor else "Mtumiaji"
            actor_username = actor[1] if actor else ""

            cursor.execute(
                """
                INSERT INTO notifications (
                    recipient_id,
                    actor_id,
                    type,
                    subscription_id,
                    message
                )
                VALUES (%s, %s, 'subscribe', %s, %s)
                """,
                (
                    user_id,
                    current_user_id,
                    subscription_id,
                    f"{actor_name} (@{actor_username}) amekusubscribe."
                )
            )

        connection.commit()

        return redirect(
            url_for(
                "user_auth.public_profile",
                username=target_user[1]
            )
        )

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        raise

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@user_auth_bp.post("/users/<int:user_id>/unsubscribe")
def unsubscribe_user(user_id):
    current_user_id = session.get("user_id")

    if not current_user_id:
        return redirect(url_for("user_auth.login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM subscriptions
            WHERE subscriber_id = %s
              AND subscribed_to_id = %s
            """,
            (current_user_id, user_id)
        )

        connection.commit()

        cursor.execute(
            """
            SELECT username
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,)
        )

        target_user = cursor.fetchone()

        if not target_user:
            return redirect(url_for("user_feed.feed"))

        return redirect(
            url_for(
                "user_auth.public_profile",
                username=target_user[0]
            )
        )

    finally:
        if connection:
            connection.close()


@user_auth_bp.get("/profile")
def profile():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("user_auth.login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                full_name,
                username,
                email,
                profile_image_url,
                cover_image_url,
                bio,
                status,
                created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user or user[7] != "active":
            session.clear()
            return redirect(url_for("user_auth.login"))

        return render_template(
            "users/profile.html",
            user=user
        )

    finally:
        if connection:
            connection.close()
