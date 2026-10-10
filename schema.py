"""
Schema + indexes - zinaendeshwa MARA MOJA tu (wakati app inapoanza,
au mara ya kwanza ensure_schema() inapoitwa), si kila request.

Kila statement ni idempotent (IF NOT EXISTS) na haifuti wala kubadilisha
data iliyopo. Kila statement inaendeshwa peke yake, kwa hiyo kama moja
ikishindwa (mfano column haipo) nyingine zinaendelea.
"""

import threading

from db import get_connection

_lock = threading.Lock()
_done = False


TABLES = [
    """
    CREATE TABLE IF NOT EXISTS content_likes (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, content_type, content_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content_saves (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, content_type, content_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content_shares (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content_reports (
        id SERIAL PRIMARY KEY,
        reporter_id INTEGER NOT NULL,
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content_interests (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, content_type, content_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS developers (
        id SERIAL PRIMARY KEY,
        name VARCHAR(150) NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


# Indexes zinatokana na columns zinazotumika kwenye queries za app.
INDEXES = [
    # Engagement (like/save/share) - hii ndiyo iliyokuwa inaleta N+1 kubwa
    "CREATE INDEX IF NOT EXISTS idx_content_likes_target ON content_likes (content_type, content_id)",
    "CREATE INDEX IF NOT EXISTS idx_content_saves_target ON content_saves (content_type, content_id)",
    "CREATE INDEX IF NOT EXISTS idx_content_shares_target ON content_shares (content_type, content_id)",
    "CREATE INDEX IF NOT EXISTS idx_content_reports_target ON content_reports (content_type, content_id)",

    # Feed
    "CREATE INDEX IF NOT EXISTS idx_posts_status_created ON posts (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_posts_user ON posts (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_quotes_status_created ON quotes (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_quotes_user ON quotes (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_songs_status_created ON songs (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_songs_user ON songs (user_id)",

    # Likes / comments
    "CREATE INDEX IF NOT EXISTS idx_post_likes_post ON post_likes (post_id)",
    "CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments (post_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_comment_likes_comment ON comment_likes (comment_id)",

    # Notifications (zinaombwa kila sekunde 30 na kila mtumiaji)
    "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_read ON notifications (recipient_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_created ON notifications (recipient_id, created_at DESC)",
]


def _run(statements):
    failed = []

    for sql in statements:
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()
            cursor.execute(sql)
            connection.commit()
            cursor.close()

        except Exception as error:
            failed.append((sql.strip().splitlines()[0][:80], str(error)))

            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

    return failed


def ensure_schema(force=False):
    """Endesha tables + indexes mara moja kwa kila process."""
    global _done

    if _done and not force:
        return True

    with _lock:
        if _done and not force:
            return True

        statements = TABLES + INDEXES
        failed = _run(statements)

        for label, error in failed:
            print(f"[schema] imeshindwa: {label} -> {error}")

        # Kama angalau statement moja ilifanikiwa, DB inapatikana: tunaweka
        # kuwa imekamilika (index moja ikishindwa isituzuie). Kama zote
        # zimeshindwa (mfano DB haipatikani) tutajaribu tena baadaye.
        if len(failed) < len(statements):
            _done = True

        return not failed
