from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from db import get_connection


user_feed_bp = Blueprint("user_feed", __name__)


def close_connection(connection):
    if connection:
        try:
            connection.close()
        except Exception:
            pass


def is_connection_error(exc):
    return type(exc).__name__ in (
        "InterfaceError",
        "OperationalError",
        "ConnectionError",
    )


@user_feed_bp.get("/feed")
def feed():
    if not session.get("user_id"):
        return redirect(url_for("user_auth.login"))

    categories = []
    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT name, slug
            FROM categories
            ORDER BY name ASC
        """)
        categories = [
            {"name": row[0], "slug": row[1]}
            for row in cursor.fetchall()
        ]
    except Exception:
        categories = []
    finally:
        close_connection(connection)

    return render_template(
        "users/feed.html",
        categories=categories
    )


@user_feed_bp.get("/api/user/posts")
def get_posts():
    current_user_id = session.get("user_id")

    if not current_user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            # -------------------------------------------------
            # NORMAL POSTS
            # -------------------------------------------------
            cursor.execute("""
                SELECT
                    p.id,
                    p.content,
                    p.media_url,
                    p.media_type,
                    p.created_at,
                    u.id,
                    u.full_name,
                    u.username,
                    u.profile_image_url,
                    COUNT(pl.id) AS likes_count,
                    EXISTS(
                        SELECT 1
                        FROM post_likes my_like
                        WHERE my_like.post_id = p.id
                          AND my_like.user_id = %s
                    ) AS is_liked
                FROM posts p
                JOIN users u
                    ON u.id = p.user_id
                LEFT JOIN post_likes pl
                    ON pl.post_id = p.id
                WHERE p.status = 'published'
                  AND u.status = 'active'
                GROUP BY
                    p.id,
                    p.content,
                    p.media_url,
                    p.media_type,
                    p.created_at,
                    u.id,
                    u.full_name,
                    u.username,
                    u.profile_image_url
                ORDER BY p.created_at DESC
                LIMIT 50
            """, (current_user_id,))

            post_rows = cursor.fetchall()

            feed_items = []

            for row in post_rows:
                feed_items.append({
                    "type": "post",
                    "id": row[0],
                    "content": row[1],
                    "media_url": row[2],
                    "media_type": row[3],
                    "created_at": row[4].isoformat(),
                    "likes_count": row[9],
                    "is_liked": bool(row[10]),
                    "user": {
                        "id": row[5],
                        "full_name": row[6],
                        "username": row[7],
                        "profile_image_url": row[8]
                    }
                })

            # -------------------------------------------------
            # QUOTES
            # -------------------------------------------------
            cursor.execute("""
                SELECT
                    q.id,
                    q.text,
                    q.author,
                    q.language,
                    q.created_at,
                    q.user_id,
                    u.full_name,
                    u.username,
                    u.profile_image_url,
                    c.name AS category_name,
                    c.slug AS category_slug
                FROM quotes q
                LEFT JOIN users u
                    ON u.id = q.user_id
                LEFT JOIN categories c
                    ON c.id = q.category_id
                WHERE q.status = 'published'
                ORDER BY q.created_at DESC
                LIMIT 50
            """)

            quote_rows = cursor.fetchall()

            for row in quote_rows:
                feed_items.append({
                    "type": "quote",
                    "id": row[0],
                    "content": row[1],
                    "quote_author": row[2],
                    "language": row[3],
                    "created_at": row[4].isoformat(),
                    "user": {
                        "id": row[5],
                        "full_name": row[6] or row[2] or "Mercfy",
                        "username": row[7] or "",
                        "profile_image_url": row[8]
                    },
                    "category": row[9],
                    "category_slug": row[10],
                    "likes_count": 0,
                    "is_liked": False
                })

            # -------------------------------------------------
            # MUSIC
            # -------------------------------------------------
            cursor.execute("""
                SELECT
                    s.id,
                    s.title,
                    s.slug,
                    s.description,
                    s.lyrics,
                    s.audio_url,
                    s.cover_url,
                    s.duration_seconds,
                    s.genre,
                    s.language,
                    s.release_date,
                    s.play_count,
                    s.download_count,
                    s.created_at,

                    u.id,
                    u.full_name,
                    u.username,
                    u.profile_image_url,

                    a.id,
                    a.name,
                    a.slug,
                    a.image_url,
                    a.country,

                    al.id,
                    al.title,
                    al.slug,
                    al.cover_url

                FROM songs s

                JOIN users u
                    ON u.id = s.user_id

                LEFT JOIN artists a
                    ON a.id = s.artist_id

                LEFT JOIN albums al
                    ON al.id = s.album_id

                WHERE s.status = 'published'
                  AND u.status = 'active'

                ORDER BY s.created_at DESC
                LIMIT 50
            """)

            music_rows = cursor.fetchall()

            for row in music_rows:
                feed_items.append({
                    "type": "music",

                    "id": row[0],
                    "song_id": row[0],
                    "title": row[1],
                    "slug": row[2],
                    "description": row[3],
                    "lyrics": row[4],
                    "audio_url": row[5],
                    "cover_url": row[6],
                    "duration_seconds": row[7],
                    "genre": row[8],
                    "language": row[9],
                    "release_date": (
                        row[10].isoformat()
                        if row[10] else None
                    ),
                    "play_count": row[11],
                    "download_count": row[12],
                    "created_at": row[13].isoformat() if row[13] else None,

                    "user": {
                        "id": row[14],
                        "full_name": row[15],
                        "username": row[16],
                        "profile_image_url": row[17]
                    },

                    "artist": {
                        "id": row[18],
                        "name": row[19],
                        "slug": row[20],
                        "image_url": row[21],
                        "country": row[22]
                    } if row[18] else None,

                    "album": {
                        "id": row[23],
                        "title": row[24],
                        "slug": row[25],
                        "cover_url": row[26]
                    } if row[23] else None,

                    # Music does not yet use post_likes.
                    "likes_count": 0,
                    "is_liked": False
                })

            cursor.close()

            # -------------------------------------------------
            # MERGE POSTS + MUSIC BY CREATED TIME
            # -------------------------------------------------
            feed_items.sort(
                key=lambda item: item["created_at"],
                reverse=True
            )

            feed_items = feed_items[:50]

            return jsonify({
                "success": True,
                "posts": feed_items
            })

        except Exception as exc:
            if attempt == 0 and is_connection_error(exc):
                continue
            raise

        finally:
            close_connection(connection)
@user_feed_bp.post("/api/user/posts/<int:post_id>/like")
def like_post(post_id):
    current_user_id = session.get("user_id")

    if not current_user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    p.id,
                    p.user_id,
                    p.status,
                    u.username
                FROM posts p
                JOIN users u
                    ON u.id = p.user_id
                WHERE p.id = %s
                  AND u.status = 'active'
                LIMIT 1
            """, (post_id,))

            post = cursor.fetchone()

            if not post or post[2] != "published":
                return jsonify({
                    "error": "Post not found"
                }), 404

            post_owner_id = post[1]
            post_owner_username = post[3]

            cursor.execute("""
                INSERT INTO post_likes (
                    post_id,
                    user_id
                )
                VALUES (%s, %s)
                ON CONFLICT (post_id, user_id)
                DO NOTHING
                RETURNING id
            """, (
                post_id,
                current_user_id
            ))

            new_like = cursor.fetchone()

            if new_like and post_owner_id != current_user_id:
                cursor.execute("""
                    SELECT
                        full_name,
                        username
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                """, (current_user_id,))

                actor = cursor.fetchone()

                actor_name = actor[0] if actor else "Mtumiaji"
                actor_username = actor[1] if actor else ""

                cursor.execute("""
                    INSERT INTO notifications (
                        recipient_id,
                        actor_id,
                        type,
                        post_id,
                        message
                    )
                    VALUES (%s, %s, 'like', %s, %s)
                """, (
                    post_owner_id,
                    current_user_id,
                    post_id,
                    f"{actor_name} (@{actor_username}) amependa post yako."
                ))

            cursor.execute("""
                SELECT COUNT(*)
                FROM post_likes
                WHERE post_id = %s
            """, (post_id,))

            likes_count = cursor.fetchone()[0]

            connection.commit()

            return jsonify({
                "success": True,
                "liked": True,
                "likes_count": likes_count,
                "notification_created": bool(
                    new_like and post_owner_id != current_user_id
                )
            })

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.post("/api/user/posts/<int:post_id>/unlike")
def unlike_post(post_id):
    current_user_id = session.get("user_id")

    if not current_user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                DELETE FROM post_likes
                WHERE post_id = %s
                  AND user_id = %s
            """, (
                post_id,
                current_user_id
            ))

            connection.commit()

            cursor.execute("""
                SELECT COUNT(*)
                FROM post_likes
                WHERE post_id = %s
            """, (post_id,))

            likes_count = cursor.fetchone()[0]

            return jsonify({
                "success": True,
                "liked": False,
                "likes_count": likes_count
            })

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.get("/api/user/posts/<int:post_id>/likes")
def get_post_likes(post_id):
    if not session.get("user_id"):
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT COUNT(*)
                FROM post_likes
                WHERE post_id = %s
            """, (post_id,))

            likes_count = cursor.fetchone()[0]

            return jsonify({
                "success": True,
                "post_id": post_id,
                "likes_count": likes_count
            })

        except Exception as exc:
            if attempt == 0 and is_connection_error(exc):
                continue
            raise

        finally:
            close_connection(connection)


@user_feed_bp.get("/api/user/notifications")
def get_notifications():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    n.id,
                    n.type,
                    n.message,
                    n.is_read,
                    n.created_at,
                    n.post_id,
                    n.subscription_id,
                    a.id,
                    a.full_name,
                    a.username,
                    a.profile_image_url
                FROM notifications n
                LEFT JOIN users a
                    ON a.id = n.actor_id
                WHERE n.recipient_id = %s
                ORDER BY n.created_at DESC
                LIMIT 50
            """, (user_id,))

            rows = cursor.fetchall()

            notifications = []

            for row in rows:
                notifications.append({
                    "id": row[0],
                    "type": row[1],
                    "message": row[2],
                    "is_read": row[3],
                    "created_at": row[4].isoformat(),
                    "post_id": row[5],
                    "subscription_id": row[6],
                    "actor": {
                        "id": row[7],
                        "full_name": row[8],
                        "username": row[9],
                        "profile_image_url": row[10]
                    } if row[7] is not None else None
                })

            return jsonify({
                "success": True,
                "notifications": notifications
            })

        except Exception as exc:
            if attempt == 0 and is_connection_error(exc):
                continue
            raise

        finally:
            close_connection(connection)


@user_feed_bp.get("/api/user/notifications/unread-count")
def get_unread_notification_count():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT COUNT(*)
                FROM notifications
                WHERE recipient_id = %s
                  AND is_read = FALSE
            """, (user_id,))

            unread_count = cursor.fetchone()[0]

            return jsonify({
                "success": True,
                "unread_count": unread_count
            })

        except Exception as exc:
            if attempt == 0 and is_connection_error(exc):
                continue
            raise

        finally:
            close_connection(connection)


@user_feed_bp.post(
    "/api/user/notifications/<int:notification_id>/read"
)
def mark_notification_read(notification_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE id = %s
                  AND recipient_id = %s
            """, (
                notification_id,
                user_id
            ))

            updated = cursor.rowcount

            connection.commit()

            return jsonify({
                "success": True,
                "updated": updated
            })

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.post("/api/user/notifications/read-all")
def mark_all_notifications_read():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE recipient_id = %s
                  AND is_read = FALSE
            """, (user_id,))

            updated = cursor.rowcount

            connection.commit()

            return jsonify({
                "success": True,
                "updated": updated
            })

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.post("/create_post")
def create_post():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("user_auth.login"))

    content = request.form.get("content", "").strip()
    # Category: user anaweza kuandika jina moja kwa moja (si select tu)
    category_raw = request.form.get("category", "").strip()[:100]
    language = (request.form.get("language") or "sw").strip()[:10] or "sw"
    author_override = request.form.get("author", "").strip()[:150]

    if not content:
        flash("Andika quote kabla ya kutuma.")
        return redirect(url_for("user_feed.feed"))

    if len(content) > 5000:
        flash("Quote ni ndefu sana.")
        return redirect(url_for("user_feed.feed"))

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT full_name, username, status
                FROM users
                WHERE id = %s
                LIMIT 1
            """, (user_id,))

            user = cursor.fetchone()

            if not user or user[2] != "active":
                session.clear()
                return redirect(url_for("user_auth.login"))

            full_name = user[0] or ""
            username = user[1] or ""
            author = author_override or full_name or username or "User"

            # Category: tafuta kwa jina/slug, au unda mpya kama user ameandika
            category_id = None
            if category_raw:
                import re as _re
                slug = _re.sub(
                    r"[^a-z0-9]+",
                    "-",
                    category_raw.lower()
                ).strip("-")[:80] or "general"

                cursor.execute("""
                    SELECT id
                    FROM categories
                    WHERE LOWER(slug) = LOWER(%s)
                       OR LOWER(name) = LOWER(%s)
                    LIMIT 1
                """, (slug, category_raw))
                cat = cursor.fetchone()

                if cat:
                    category_id = cat[0]
                else:
                    cursor.execute("""
                        INSERT INTO categories (name, slug)
                        VALUES (%s, %s)
                        RETURNING id
                    """, (category_raw, slug))
                    new_cat = cursor.fetchone()
                    if new_cat:
                        category_id = new_cat[0]

            cursor.execute("""
                INSERT INTO quotes (
                    text,
                    author,
                    category_id,
                    language,
                    status,
                    user_id
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'published',
                    %s
                )
                RETURNING id
            """, (
                content,
                author,
                category_id,
                language,
                user_id
            ))

            quote_id = cursor.fetchone()[0]
            connection.commit()

            flash("Quote imechapishwa na inaonekana kwenye API kwa developers.")
            return redirect(url_for("user_feed.feed"))

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)

# ============================================================
# COMMENTS + UNLIMITED NESTED REPLIES
# ============================================================

@user_feed_bp.post("/api/user/posts/<int:post_id>/comments")
def create_comment(post_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    content = request.form.get("content", "").strip()

    if not content:
        data = request.get_json(silent=True) or {}
        content = str(data.get("content", "")).strip()

    if not content:
        return jsonify({
            "error": "Comment haiwezi kuwa tupu."
        }), 400

    if len(content) > 5000:
        return jsonify({
            "error": "Comment ni ndefu sana."
        }), 400

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    p.id,
                    p.user_id,
                    p.status,
                    u.status
                FROM posts p
                JOIN users u
                    ON u.id = p.user_id
                WHERE p.id = %s
                LIMIT 1
            """, (post_id,))

            post = cursor.fetchone()

            if not post or post[2] != "published" or post[3] != "active":
                return jsonify({
                    "error": "Post not found"
                }), 404

            cursor.execute("""
                SELECT status
                FROM users
                WHERE id = %s
                LIMIT 1
            """, (user_id,))

            user = cursor.fetchone()

            if not user or user[0] != "active":
                session.clear()
                return jsonify({
                    "error": "Account is not active"
                }), 403

            cursor.execute("""
                INSERT INTO post_comments (
                    post_id,
                    user_id,
                    parent_comment_id,
                    content,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    NULL,
                    %s,
                    'published'
                )
                RETURNING id, created_at
            """, (
                post_id,
                user_id,
                content
            ))

            comment = cursor.fetchone()
            comment_id = comment[0]

            if post[1] != user_id:
                cursor.execute("""
                    SELECT
                        full_name,
                        username
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                """, (user_id,))

                actor = cursor.fetchone()

                actor_name = actor[0] if actor else "Mtumiaji"
                actor_username = actor[1] if actor else ""

                cursor.execute("""
                    INSERT INTO notifications (
                        recipient_id,
                        actor_id,
                        type,
                        post_id,
                        message
                    )
                    VALUES (
                        %s,
                        %s,
                        'comment',
                        %s,
                        %s
                    )
                """, (
                    post[1],
                    user_id,
                    post_id,
                    f"{actor_name} (@{actor_username}) ametoa comment kwenye post yako."
                ))

            connection.commit()

            return jsonify({
                "success": True,
                "comment": {
                    "id": comment_id,
                    "post_id": post_id,
                    "parent_comment_id": None,
                    "content": content,
                    "created_at": comment[1].isoformat()
                }
            }), 201

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.post("/api/user/comments/<int:comment_id>/reply")
def create_reply(comment_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    content = request.form.get("content", "").strip()

    if not content:
        data = request.get_json(silent=True) or {}
        content = str(data.get("content", "")).strip()

    if not content:
        return jsonify({
            "error": "Reply haiwezi kuwa tupu."
        }), 400

    if len(content) > 5000:
        return jsonify({
            "error": "Reply ni ndefu sana."
        }), 400

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    c.id,
                    c.post_id,
                    c.user_id,
                    c.parent_comment_id,
                    c.status,
                    p.status,
                    u.status
                FROM post_comments c
                JOIN posts p
                    ON p.id = c.post_id
                JOIN users u
                    ON u.id = c.user_id
                WHERE c.id = %s
                LIMIT 1
            """, (comment_id,))

            parent = cursor.fetchone()

            if (
                not parent
                or parent[4] != "published"
                or parent[5] != "published"
                or parent[6] != "active"
            ):
                return jsonify({
                    "error": "Comment not found"
                }), 404

            post_id = parent[1]
            parent_user_id = parent[2]

            cursor.execute("""
                SELECT status
                FROM users
                WHERE id = %s
                LIMIT 1
            """, (user_id,))

            user = cursor.fetchone()

            if not user or user[0] != "active":
                session.clear()
                return jsonify({
                    "error": "Account is not active"
                }), 403

            # IMPORTANT:
            # This points directly to the exact comment/reply being answered.
            # Therefore nesting can continue indefinitely.
            cursor.execute("""
                INSERT INTO post_comments (
                    post_id,
                    user_id,
                    parent_comment_id,
                    content,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'published'
                )
                RETURNING id, created_at
            """, (
                post_id,
                user_id,
                comment_id,
                content
            ))

            reply = cursor.fetchone()
            reply_id = reply[0]

            if parent_user_id != user_id:
                cursor.execute("""
                    SELECT
                        full_name,
                        username
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                """, (user_id,))

                actor = cursor.fetchone()

                actor_name = actor[0] if actor else "Mtumiaji"
                actor_username = actor[1] if actor else ""

                cursor.execute("""
                    INSERT INTO notifications (
                        recipient_id,
                        actor_id,
                        type,
                        post_id,
                        message
                    )
                    VALUES (
                        %s,
                        %s,
                        'reply',
                        %s,
                        %s
                    )
                """, (
                    parent_user_id,
                    user_id,
                    post_id,
                    f"{actor_name} (@{actor_username}) amejibu comment yako."
                ))

            connection.commit()

            return jsonify({
                "success": True,
                "comment": {
                    "id": reply_id,
                    "post_id": post_id,
                    "parent_comment_id": comment_id,
                    "content": content,
                    "created_at": reply[1].isoformat()
                }
            }), 201

        except Exception as exc:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)


@user_feed_bp.get("/api/user/posts/<int:post_id>/comments")
def get_post_comments(post_id):
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    user_id = int(session["user_id"])
    conn = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                pc.id,
                pc.post_id,
                pc.user_id,
                pc.parent_comment_id,
                pc.content,
                pc.created_at,

                u.username,
                u.full_name,
                u.profile_image_url,

                (
                    SELECT COUNT(*)
                    FROM comment_likes cl
                    WHERE cl.comment_id = pc.id
                ) AS likes_count,

                EXISTS (
                    SELECT 1
                    FROM comment_likes cl2
                    WHERE cl2.comment_id = pc.id
                      AND cl2.user_id = %s
                ) AS is_liked

            FROM post_comments pc
            JOIN users u
                ON u.id = pc.user_id

            WHERE pc.post_id = %s
              AND pc.status = 'published'
              AND u.status = 'active'

            ORDER BY pc.created_at ASC, pc.id ASC
        """, (user_id, post_id))

        rows = cur.fetchall()

        nodes = {}

        for row in rows:
            node = {
                "id": row[0],
                "post_id": row[1],
                "user_id": row[2],
                "parent_comment_id": row[3],
                "content": row[4],
                "created_at": row[5].isoformat()
                    if row[5] else None,

                "user": {
                    "id": row[2],
                    "username": row[6],
                    "full_name": row[7],
                    "profile_image_url": row[8]
                },

                "likes_count": int(row[9] or 0),
                "is_liked": bool(row[10]),

                "children": []
            }

            nodes[row[0]] = node

        roots = []

        for row in rows:
            node = nodes[row[0]]
            parent_id = row[3]

            if parent_id is None:
                roots.append(node)
            elif parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)

        return jsonify({
            "success": True,
            "post_id": post_id,
            "comments_count": len(rows),
            "comments": roots
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()

        print("GET COMMENTS ERROR:", repr(e))

        return jsonify({
            "success": False,
            "message": "Failed to load comments"
        }), 500

    finally:
        if conn:
            close_connection(conn)

@user_feed_bp.get("/api/user/posts/<int:post_id>/comments/count")
def get_comments_count(post_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "error": "Authentication required"
        }), 401

    for attempt in range(2):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT COUNT(*)
                FROM post_comments c
                JOIN users u
                    ON u.id = c.user_id
                WHERE c.post_id = %s
                  AND c.status = 'published'
                  AND u.status = 'active'
            """, (post_id,))

            count = cursor.fetchone()[0]

            return jsonify({
                "success": True,
                "post_id": post_id,
                "comments_count": count
            })

        except Exception as exc:
            if attempt == 0 and is_connection_error(exc):
                continue

            raise

        finally:
            close_connection(connection)

# ============================================================
# COMMENT / REPLY LIKES
# ============================================================

@user_feed_bp.post("/api/user/comments/<int:comment_id>/like")
def like_comment(comment_id):
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    user_id = int(session["user_id"])
    conn = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        # Verify comment exists and is visible
        cur.execute("""
            SELECT
                pc.id,
                pc.user_id,
                pc.post_id,
                pc.parent_comment_id,
                pc.status,
                u.status AS user_status
            FROM post_comments pc
            JOIN users u ON u.id = pc.user_id
            WHERE pc.id = %s
              AND pc.status = 'published'
              AND u.status = 'active'
        """, (comment_id,))

        comment = cur.fetchone()

        if not comment:
            return jsonify({
                "success": False,
                "message": "Comment not found"
            }), 404

        # Check current user is active
        cur.execute("""
            SELECT status
            FROM users
            WHERE id = %s
        """, (user_id,))

        current_user = cur.fetchone()

        if not current_user or current_user["status"] != "active":
            return jsonify({
                "success": False,
                "message": "Account unavailable"
            }), 403

        # Add like only if it does not already exist
        cur.execute("""
            INSERT INTO comment_likes (
                comment_id,
                user_id
            )
            VALUES (%s, %s)
            ON CONFLICT (comment_id, user_id)
            DO NOTHING
            RETURNING id
        """, (comment_id, user_id))

        inserted = cur.fetchone()

        # Notify comment/reply owner only for a new like
        if inserted and comment["user_id"] != user_id:
            cur.execute("""
                INSERT INTO notifications (
                    recipient_id,
                    actor_id,
                    type,
                    post_id,
                    message
                )
                VALUES (
                    %s,
                    %s,
                    'like',
                    %s,
                    %s
                )
            """, (
                comment["user_id"],
                user_id,
                comment["post_id"],
                "Alipenda comment yako"
            ))

        # Get latest count
        cur.execute("""
            SELECT COUNT(*) AS likes_count
            FROM comment_likes
            WHERE comment_id = %s
        """, (comment_id,))

        result = cur.fetchone()

        conn.commit()

        return jsonify({
            "success": True,
            "liked": True,
            "likes_count": int(result["likes_count"]),
            "new_like": bool(inserted)
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()

        return jsonify({
            "success": False,
            "message": "Failed to like comment"
        }), 500

    finally:
        if conn:
            close_connection(conn)


@user_feed_bp.post("/api/user/comments/<int:comment_id>/unlike")
def unlike_comment(comment_id):
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    user_id = int(session["user_id"])
    conn = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM comment_likes
            WHERE comment_id = %s
              AND user_id = %s
        """, (comment_id, user_id))

        cur.execute("""
            SELECT COUNT(*) AS likes_count
            FROM comment_likes
            WHERE comment_id = %s
        """, (comment_id,))

        result = cur.fetchone()

        conn.commit()

        return jsonify({
            "success": True,
            "liked": False,
            "likes_count": int(result["likes_count"])
        }), 200

    except Exception:
        if conn:
            conn.rollback()

        return jsonify({
            "success": False,
            "message": "Failed to unlike comment"
        }), 500

    finally:
        if conn:
            close_connection(conn)


# ============================================================
# QUOTE / MUSIC OWNER ACTIONS + REPORT / INTEREST
# ============================================================

def ensure_report_tables(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_reports (
                id SERIAL PRIMARY KEY,
                reporter_id INTEGER NOT NULL,
                content_type VARCHAR(20) NOT NULL,
                content_id INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_interests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                content_type VARCHAR(20) NOT NULL,
                content_id INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, content_type, content_id)
            )
        """)
        connection.commit()
    finally:
        cursor.close()


@user_feed_bp.delete("/api/user/quotes/<int:quote_id>")
@user_feed_bp.post("/api/user/quotes/<int:quote_id>/delete")
def delete_quote(quote_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT user_id FROM quotes WHERE id = %s LIMIT 1",
            (quote_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Quote not found"}), 404
        if int(row[0] or 0) != int(user_id):
            return jsonify({"success": False, "message": "Forbidden"}), 403

        cursor.execute("DELETE FROM quotes WHERE id = %s", (quote_id,))
        connection.commit()
        return jsonify({"success": True, "message": "Quote imefutwa"})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        close_connection(connection)


@user_feed_bp.post("/api/user/quotes/<int:quote_id>/edit")
def edit_quote(quote_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or request.form.get("content") or "").strip()
    category_raw = (data.get("category") or request.form.get("category") or "").strip()[:100]
    author = (data.get("author") or request.form.get("author") or "").strip()[:150]
    language = (data.get("language") or request.form.get("language") or "").strip()[:10]

    if not content:
        return jsonify({"success": False, "message": "Quote text required"}), 400
    if len(content) > 5000:
        return jsonify({"success": False, "message": "Quote ni ndefu sana"}), 400

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT user_id FROM quotes WHERE id = %s LIMIT 1",
            (quote_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Quote not found"}), 404
        if int(row[0] or 0) != int(user_id):
            return jsonify({"success": False, "message": "Forbidden"}), 403

        category_id = None
        if category_raw:
            import re as _re
            slug = _re.sub(r"[^a-z0-9]+", "-", category_raw.lower()).strip("-")[:80] or "general"
            cursor.execute(
                """
                SELECT id FROM categories
                WHERE LOWER(slug) = LOWER(%s) OR LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (slug, category_raw),
            )
            cat = cursor.fetchone()
            if cat:
                category_id = cat[0]
            else:
                cursor.execute(
                    "INSERT INTO categories (name, slug) VALUES (%s, %s) RETURNING id",
                    (category_raw, slug),
                )
                category_id = cursor.fetchone()[0]

        sets = ["text = %s"]
        params = [content]
        if author:
            sets.append("author = %s")
            params.append(author)
        if language:
            sets.append("language = %s")
            params.append(language)
        if category_raw:
            sets.append("category_id = %s")
            params.append(category_id)
        params.append(quote_id)

        cursor.execute(
            f"UPDATE quotes SET {', '.join(sets)} WHERE id = %s",
            params,
        )
        connection.commit()
        return jsonify({"success": True, "message": "Quote imesasishwa"})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        close_connection(connection)


@user_feed_bp.post("/api/user/content/report")
def report_content():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    content_type = (data.get("content_type") or "").strip().lower()
    content_id = data.get("content_id")
    reason = (data.get("reason") or "").strip()[:500]

    if content_type not in ("quote", "music", "post") or not content_id:
        return jsonify({"success": False, "message": "Invalid content"}), 400

    connection = None
    try:
        connection = get_connection()
        ensure_report_tables(connection)
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO content_reports (reporter_id, content_type, content_id, reason)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, content_type, int(content_id), reason or None),
        )
        connection.commit()
        return jsonify({"success": True, "message": "Report imetumwa. Asante."})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        close_connection(connection)


@user_feed_bp.post("/api/user/content/interest")
def toggle_interest():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    content_type = (data.get("content_type") or "").strip().lower()
    content_id = data.get("content_id")

    if content_type not in ("quote", "music", "post") or not content_id:
        return jsonify({"success": False, "message": "Invalid content"}), 400

    connection = None
    try:
        connection = get_connection()
        ensure_report_tables(connection)
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id FROM content_interests
            WHERE user_id = %s AND content_type = %s AND content_id = %s
            LIMIT 1
            """,
            (user_id, content_type, int(content_id)),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute("DELETE FROM content_interests WHERE id = %s", (existing[0],))
            connection.commit()
            return jsonify({"success": True, "interested": False, "message": "Imeondolewa kwenye interested"})
        cursor.execute(
            """
            INSERT INTO content_interests (user_id, content_type, content_id)
            VALUES (%s, %s, %s)
            """,
            (user_id, content_type, int(content_id)),
        )
        connection.commit()
        return jsonify({"success": True, "interested": True, "message": "Imeongezwa kwenye interested"})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        close_connection(connection)
