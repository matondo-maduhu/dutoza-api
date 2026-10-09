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


# ============================================================
# SETTINGS
# ============================================================

@user_auth_bp.get("/settings")
def settings():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("user_auth.login"))

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, full_name, username, email,
                   profile_image_url, cover_image_url, bio, status
            FROM users WHERE id = %s LIMIT 1
            """,
            (user_id,),
        )
        user = cursor.fetchone()
        if not user or user[7] != "active":
            session.clear()
            return redirect(url_for("user_auth.login"))
        return render_template("users/settings.html", user=user)
    finally:
        if connection:
            connection.close()


@user_auth_bp.post("/settings/profile")
def settings_update_profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("user_auth.login"))

    full_name = request.form.get("full_name", "").strip()[:150]
    bio = request.form.get("bio", "").strip()[:500]
    email = request.form.get("email", "").strip().lower()[:150]

    if not full_name or len(full_name) < 2:
        flash("Jina linahitajika.")
        return redirect(url_for("user_auth.settings"))

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        if email:
            cursor.execute(
                """
                SELECT id FROM users
                WHERE LOWER(email) = LOWER(%s) AND id != %s LIMIT 1
                """,
                (email, user_id),
            )
            if cursor.fetchone():
                flash("Email hii tayari inatumika.")
                return redirect(url_for("user_auth.settings"))

        cursor.execute(
            """
            UPDATE users
            SET full_name = %s,
                bio = %s,
                email = COALESCE(NULLIF(%s, ''), email)
            WHERE id = %s
            """,
            (full_name, bio or None, email, user_id),
        )
        connection.commit()
        session["full_name"] = full_name
        flash("Profile imesasishwa.")
    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        flash("Imeshindikana kusasisha profile.")
    finally:
        if connection:
            connection.close()

    return redirect(url_for("user_auth.settings"))


@user_auth_bp.post("/settings/username")
def settings_update_username():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("user_auth.login"))

    username = request.form.get("username", "").strip()
    if len(username) < 3 or len(username) > 50:
        flash("Username iwe herufi 3–50.")
        return redirect(url_for("user_auth.settings"))

    import re
    if not re.match(r"^[A-Za-z0-9._]+$", username):
        flash("Username: herufi, namba, . au _ tu.")
        return redirect(url_for("user_auth.settings"))

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id FROM users
            WHERE LOWER(username) = LOWER(%s) AND id != %s LIMIT 1
            """,
            (username, user_id),
        )
        if cursor.fetchone():
            flash("Username hii tayari imechukuliwa.")
            return redirect(url_for("user_auth.settings"))

        cursor.execute(
            "UPDATE users SET username = %s WHERE id = %s",
            (username, user_id),
        )
        connection.commit()
        session["username"] = username
        flash("Username imebadilishwa.")
    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        flash("Imeshindikana kubadili username.")
    finally:
        if connection:
            connection.close()

    return redirect(url_for("user_auth.settings"))


@user_auth_bp.post("/settings/password")
def settings_update_password():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("user_auth.login"))

    current = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if len(new_password) < 8:
        flash("Password mpya iwe angalau herufi 8.")
        return redirect(url_for("user_auth.settings"))
    if new_password != confirm:
        flash("Password mpya hazilingani.")
        return redirect(url_for("user_auth.settings"))

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT password_hash FROM users WHERE id = %s LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row or not check_password_hash(row[0], current):
            flash("Password ya sasa si sahihi.")
            return redirect(url_for("user_auth.settings"))

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_password), user_id),
        )
        connection.commit()
        flash("Password imebadilishwa.")
    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        flash("Imeshindikana kubadili password.")
    finally:
        if connection:
            connection.close()

    return redirect(url_for("user_auth.settings"))


@user_auth_bp.post("/settings/delete-account")
def settings_delete_account():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("user_auth.login"))

    password = request.form.get("password", "")
    confirm_text = request.form.get("confirm_text", "").strip().upper()

    if confirm_text != "DELETE":
        flash('Andika neno "DELETE" ili kuthibitisha.')
        return redirect(url_for("user_auth.settings"))

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT password_hash FROM users WHERE id = %s LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row or not check_password_hash(row[0], password):
            flash("Password si sahihi.")
            return redirect(url_for("user_auth.settings"))

        # Soft-delete: deactivate account
        cursor.execute(
            """
            UPDATE users
            SET status = 'deleted',
                email = CONCAT('deleted_', id, '_', email),
                username = CONCAT('deleted_', id, '_', username)
            WHERE id = %s
            """,
            (user_id,),
        )
        connection.commit()
        session.clear()
        flash("Akaunti imefutwa.")
        return redirect(url_for("user_auth.login"))
    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        flash("Imeshindikana kufuta akaunti.")
        return redirect(url_for("user_auth.settings"))
    finally:
        if connection:
            connection.close()


@user_auth_bp.get("/about")
def about():
    return render_template(
        "users/static_page.html",
        page_title="About",
        page_heading="Kuhusu Incredibles",
        page_body="""
        <p><strong>Incredibles</strong> ni jukwaa la kushiriki quotes na muziki.
        Watumiaji wanachapisha content; developers wanaitumia kupitia API.</p>
        <p>Lengo letu ni kutoa catalog safi ya quotes na music kwa apps na watumiaji.</p>
        """,
    )


@user_auth_bp.get("/terms")
def terms():
    return render_template(
        "users/static_page.html",
        page_title="Terms",
        page_heading="Terms & Conditions",
        page_body="""
        <p>Kwa kutumia Incredibles, unakubali:</p>
        <ul>
            <li>Usichapishe content haramu, ya chuki, au inayokiuka haki miliki.</li>
            <li>Uwe na haki ya content unayopakia (quotes, audio, cover).</li>
            <li>Content iliyochapishwa inaweza kuonekana kwenye API ya developers.</li>
            <li>Tunaweza kuondoa content au akaunti inayokiuka sheria hizi.</li>
        </ul>
        <p>Tunaweza kusasisha terms hizi; matumizi ya kuendelea yanamaanisha unakubali mabadiliko.</p>
        """,
    )


@user_auth_bp.get("/privacy")
def privacy():
    return render_template(
        "users/static_page.html",
        page_title="Privacy",
        page_heading="Privacy Policy",
        page_body="""
        <p>Tunahifadhi taarifa kama jina, username, email, na content unayochapisha.</p>
        <ul>
            <li>Hatuzuii data yako binafsi kwa wauzaji wa tatu kwa matangazo.</li>
            <li>API keys na developer data zinatengwa na akaunti za watumiaji wa kawaida.</li>
            <li>Unaweza kuhariri profile yako au kufuta akaunti kwenye Settings.</li>
            <li>Baada ya kufuta akaunti, status inabadilika na login haifanyi kazi tena.</li>
        </ul>
        """,
    )


@user_auth_bp.get("/help")
def help_centre():
    return render_template(
        "users/static_page.html",
        page_title="Help",
        page_heading="Help Centre / Contact",
        page_body="""
        <p><strong>Maswali ya kawaida</strong></p>
        <ul>
            <li><strong>Jinsi ya kupost quote?</strong> Fungua Home → bonyeza + au alama ya quote.</li>
            <li><strong>Jinsi ya kupost music?</strong> Bonyeza alama ya muziki kwenye composer.</li>
            <li><strong>Developer API?</strong> Tembelea /developers kwa key na docs.</li>
        </ul>
        <p><strong>Contact us</strong></p>
        <p>Barua: support@incredibles.app</p>
        <p>Tutaongeza form ya contact moja kwa moja baadaye.</p>
        """,
    )
