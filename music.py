from flask import Blueprint, jsonify, request

from db import get_connection
from auth import require_api_key


music_bp = Blueprint("music", __name__)


def serialize_song(row):
    """
    row indices 0-23 as before, then:
      24 s.user_id
      25 u.full_name
      26 u.username
      27 u.profile_image_url
    """
    user_id = row[24] if len(row) > 24 else None
    data = {
        "id": row[0],
        "title": row[1],
        "slug": row[2],
        "description": row[3],
        "lyrics": row[4],
        "audio_url": row[5],
        "cover_url": row[6],
        "duration_seconds": row[7],
        "track_number": row[8],
        "genre": row[9],
        "language": row[10],
        "release_date": (
            row[11].isoformat()
            if row[11]
            else None
        ),
        "play_count": row[12],
        "download_count": row[13],
        "artist": {
            "id": row[14],
            "name": row[15],
            "slug": row[16],
            "image_url": row[17],
            "country": row[18]
        } if row[14] else None,
        "album": {
            "id": row[19],
            "title": row[20],
            "slug": row[21],
            "cover_url": row[22]
        } if row[19] else None,
        "created_at": (
            row[23].isoformat()
            if row[23]
            else None
        ),
        "user_id": user_id,
        "source": "user" if user_id else "admin",
    }
    if user_id and len(row) > 26:
        data["user"] = {
            "id": user_id,
            "full_name": row[25],
            "username": row[26],
            "profile_image_url": row[27] if len(row) > 27 else None,
        }
    else:
        data["user"] = None
    return data


SONG_SELECT = """
    SELECT
        s.id,
        s.title,
        s.slug,
        s.description,
        s.lyrics,
        s.audio_url,
        s.cover_url,
        s.duration_seconds,
        s.track_number,
        s.genre,
        s.language,
        s.release_date,
        s.play_count,
        s.download_count,

        ar.id,
        ar.name,
        ar.slug,
        ar.image_url,
        ar.country,

        al.id,
        al.title,
        al.slug,
        al.cover_url,

        s.created_at,
        s.user_id,
        u.full_name,
        u.username,
        u.profile_image_url

    FROM songs s

    LEFT JOIN artists ar
        ON ar.id = s.artist_id

    LEFT JOIN albums al
        ON al.id = s.album_id

    LEFT JOIN users u
        ON u.id = s.user_id
"""


@music_bp.get("/")
@require_api_key
def get_music():
    connection = None

    try:
        page = max(
            request.args.get(
                "page",
                1,
                type=int
            ),
            1
        )

        per_page = request.args.get(
            "per_page",
            20,
            type=int
        )

        per_page = min(
            max(per_page, 1),
            100
        )

        search = request.args.get(
            "q",
            ""
        ).strip()

        artist = request.args.get(
            "artist",
            ""
        ).strip()

        album = request.args.get(
            "album",
            ""
        ).strip()

        genre = request.args.get(
            "genre",
            ""
        ).strip()

        language = request.args.get(
            "language",
            ""
        ).strip()

        user_id_filter = request.args.get(
            "user_id",
            type=int
        )
        source = request.args.get(
            "source",
            ""
        ).strip().lower()

        offset = (
            page - 1
        ) * per_page

        conditions = [
            "s.status = 'published'"
        ]

        params = []

        if search:
            conditions.append("""
                (
                    s.title ILIKE %s
                    OR s.description ILIKE %s
                    OR s.genre ILIKE %s
                    OR ar.name ILIKE %s
                    OR u.username ILIKE %s
                    OR u.full_name ILIKE %s
                )
            """)

            search_value = f"%{search}%"

            params.extend([
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
            ])

        if artist:
            conditions.append("""
                (
                    LOWER(ar.slug) = LOWER(%s)
                    OR CAST(ar.id AS TEXT) = %s
                )
            """)

            params.extend([
                artist,
                artist
            ])

        if album:
            conditions.append("""
                (
                    LOWER(al.slug) = LOWER(%s)
                    OR CAST(al.id AS TEXT) = %s
                )
            """)

            params.extend([
                album,
                album
            ])

        if genre:
            conditions.append(
                "LOWER(s.genre) = LOWER(%s)"
            )

            params.append(genre)

        if language:
            conditions.append(
                "LOWER(s.language) = LOWER(%s)"
            )

            params.append(language)

        if user_id_filter:
            conditions.append("s.user_id = %s")
            params.append(user_id_filter)

        if source == "user":
            conditions.append("s.user_id IS NOT NULL")
        elif source == "admin":
            conditions.append("s.user_id IS NULL")

        where_sql = " AND ".join(
            conditions
        )

        connection = get_connection()
        cursor = connection.cursor()

        count_sql = f"""
            SELECT COUNT(*)
            FROM songs s

            LEFT JOIN artists ar
                ON ar.id = s.artist_id

            LEFT JOIN albums al
                ON al.id = s.album_id

            LEFT JOIN users u
                ON u.id = s.user_id

            WHERE {where_sql}
        """

        cursor.execute(
            count_sql,
            params
        )

        total = cursor.fetchone()[0]

        data_sql = f"""
            {SONG_SELECT}

            WHERE {where_sql}

            ORDER BY
                s.release_date DESC NULLS LAST,
                s.id DESC

            LIMIT %s
            OFFSET %s
        """

        cursor.execute(
            data_sql,
            params + [
                per_page,
                offset
            ]
        )

        rows = cursor.fetchall()

        data = [
            serialize_song(row)
            for row in rows
        ]

        return jsonify({
            "success": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (
                (total + per_page - 1)
                // per_page
                if total
                else 0
            ),
            "data": data
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.get("/artists")
@require_api_key
def get_artists():
    connection = None

    try:
        page = max(
            request.args.get(
                "page",
                1,
                type=int
            ),
            1
        )

        per_page = request.args.get(
            "per_page",
            20,
            type=int
        )

        per_page = min(
            max(per_page, 1),
            100
        )

        search = request.args.get(
            "q",
            ""
        ).strip()

        offset = (
            page - 1
        ) * per_page

        connection = get_connection()
        cursor = connection.cursor()

        conditions = [
            "ar.status = 'published'"
        ]

        params = []

        if search:
            conditions.append("""
                (
                    ar.name ILIKE %s
                    OR ar.bio ILIKE %s
                )
            """)

            value = f"%{search}%"

            params.extend([
                value,
                value
            ])

        where_sql = " AND ".join(
            conditions
        )

        cursor.execute(
            f"""
                SELECT COUNT(*)
                FROM artists ar
                WHERE {where_sql}
            """,
            params
        )

        total = cursor.fetchone()[0]

        cursor.execute(
            f"""
                SELECT
                    ar.id,
                    ar.name,
                    ar.slug,
                    ar.bio,
                    ar.image_url,
                    ar.country,
                    ar.language,
                    ar.created_at,
                    COUNT(s.id) AS song_count

                FROM artists ar

                LEFT JOIN songs s
                    ON s.artist_id = ar.id
                    AND s.status = 'published'

                WHERE {where_sql}

                GROUP BY
                    ar.id,
                    ar.name,
                    ar.slug,
                    ar.bio,
                    ar.image_url,
                    ar.country,
                    ar.language,
                    ar.created_at

                ORDER BY ar.name ASC

                LIMIT %s
                OFFSET %s
            """,
            params + [
                per_page,
                offset
            ]
        )

        rows = cursor.fetchall()

        data = []

        for row in rows:
            data.append({
                "id": row[0],
                "name": row[1],
                "slug": row[2],
                "bio": row[3],
                "image_url": row[4],
                "country": row[5],
                "language": row[6],
                "created_at": (
                    row[7].isoformat()
                    if row[7]
                    else None
                ),
                "song_count": row[8]
            })

        return jsonify({
            "success": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (
                (total + per_page - 1)
                // per_page
                if total
                else 0
            ),
            "data": data
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.get("/artists/<int:artist_id>")
@require_api_key
def get_artist(artist_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
                SELECT
                    id,
                    name,
                    slug,
                    bio,
                    image_url,
                    country,
                    language,
                    created_at
                FROM artists
                WHERE id = %s
                  AND status = 'published'
            """,
            (artist_id,)
        )

        artist = cursor.fetchone()

        if not artist:
            return jsonify({
                "success": False,
                "error": "Artist not found"
            }), 404

        cursor.execute(
            f"""
                {SONG_SELECT}

                WHERE s.artist_id = %s
                  AND s.status = 'published'

                ORDER BY
                    s.release_date DESC NULLS LAST,
                    s.id DESC
            """,
            (artist_id,)
        )

        songs = [
            serialize_song(row)
            for row in cursor.fetchall()
        ]

        return jsonify({
            "success": True,
            "data": {
                "id": artist[0],
                "name": artist[1],
                "slug": artist[2],
                "bio": artist[3],
                "image_url": artist[4],
                "country": artist[5],
                "language": artist[6],
                "created_at": (
                    artist[7].isoformat()
                    if artist[7]
                    else None
                ),
                "songs": songs
            }
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.get("/albums")
@require_api_key
def get_albums():
    connection = None

    try:
        page = max(
            request.args.get(
                "page",
                1,
                type=int
            ),
            1
        )

        per_page = request.args.get(
            "per_page",
            20,
            type=int
        )

        per_page = min(
            max(per_page, 1),
            100
        )

        search = request.args.get(
            "q",
            ""
        ).strip()

        artist = request.args.get(
            "artist",
            ""
        ).strip()

        offset = (
            page - 1
        ) * per_page

        connection = get_connection()
        cursor = connection.cursor()

        conditions = [
            "al.status = 'published'"
        ]

        params = []

        if search:
            conditions.append("""
                (
                    al.title ILIKE %s
                    OR al.description ILIKE %s
                    OR ar.name ILIKE %s
                )
            """)

            value = f"%{search}%"

            params.extend([
                value,
                value,
                value
            ])

        if artist:
            conditions.append("""
                (
                    LOWER(ar.slug) = LOWER(%s)
                    OR CAST(ar.id AS TEXT) = %s
                )
            """)

            params.extend([
                artist,
                artist
            ])

        where_sql = " AND ".join(
            conditions
        )

        cursor.execute(
            f"""
                SELECT COUNT(*)
                FROM albums al

                LEFT JOIN artists ar
                    ON ar.id = al.artist_id

                WHERE {where_sql}
            """,
            params
        )

        total = cursor.fetchone()[0]

        cursor.execute(
            f"""
                SELECT
                    al.id,
                    al.title,
                    al.slug,
                    al.description,
                    al.cover_url,
                    al.release_date,
                    al.language,
                    al.created_at,

                    ar.id,
                    ar.name,
                    ar.slug,

                    COUNT(s.id) AS song_count

                FROM albums al

                LEFT JOIN artists ar
                    ON ar.id = al.artist_id

                LEFT JOIN songs s
                    ON s.album_id = al.id
                    AND s.status = 'published'

                WHERE {where_sql}

                GROUP BY
                    al.id,
                    al.title,
                    al.slug,
                    al.description,
                    al.cover_url,
                    al.release_date,
                    al.language,
                    al.created_at,
                    ar.id,
                    ar.name,
                    ar.slug

                ORDER BY
                    al.release_date DESC NULLS LAST,
                    al.id DESC

                LIMIT %s
                OFFSET %s
            """,
            params + [
                per_page,
                offset
            ]
        )

        rows = cursor.fetchall()

        data = []

        for row in rows:
            data.append({
                "id": row[0],
                "title": row[1],
                "slug": row[2],
                "description": row[3],
                "cover_url": row[4],
                "release_date": (
                    row[5].isoformat()
                    if row[5]
                    else None
                ),
                "language": row[6],
                "created_at": (
                    row[7].isoformat()
                    if row[7]
                    else None
                ),
                "artist": {
                    "id": row[8],
                    "name": row[9],
                    "slug": row[10]
                } if row[8] else None,
                "song_count": row[11]
            })

        return jsonify({
            "success": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (
                (total + per_page - 1)
                // per_page
                if total
                else 0
            ),
            "data": data
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.get("/albums/<int:album_id>")
@require_api_key
def get_album(album_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
                SELECT
                    al.id,
                    al.title,
                    al.slug,
                    al.description,
                    al.cover_url,
                    al.release_date,
                    al.language,
                    al.created_at,

                    ar.id,
                    ar.name,
                    ar.slug,
                    ar.image_url

                FROM albums al

                LEFT JOIN artists ar
                    ON ar.id = al.artist_id

                WHERE al.id = %s
                  AND al.status = 'published'
            """,
            (album_id,)
        )

        album = cursor.fetchone()

        if not album:
            return jsonify({
                "success": False,
                "error": "Album not found"
            }), 404

        cursor.execute(
            f"""
                {SONG_SELECT}

                WHERE s.album_id = %s
                  AND s.status = 'published'

                ORDER BY
                    s.track_number ASC NULLS LAST,
                    s.id ASC
            """,
            (album_id,)
        )

        songs = [
            serialize_song(row)
            for row in cursor.fetchall()
        ]

        return jsonify({
            "success": True,
            "data": {
                "id": album[0],
                "title": album[1],
                "slug": album[2],
                "description": album[3],
                "cover_url": album[4],
                "release_date": (
                    album[5].isoformat()
                    if album[5]
                    else None
                ),
                "language": album[6],
                "created_at": (
                    album[7].isoformat()
                    if album[7]
                    else None
                ),
                "artist": {
                    "id": album[8],
                    "name": album[9],
                    "slug": album[10],
                    "image_url": album[11]
                } if album[8] else None,
                "songs": songs
            }
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.get("/<int:music_id>")
@require_api_key
def get_music_by_id(music_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            f"""
                {SONG_SELECT}

                WHERE s.id = %s
                  AND s.status = 'published'
            """,
            (music_id,)
        )

        row = cursor.fetchone()

        if not row:
            return jsonify({
                "success": False,
                "error": "Song not found"
            }), 404

        return jsonify({
            "success": True,
            "data": serialize_song(row)
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.post("/<int:music_id>/play")
@require_api_key
def play_music(music_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
                UPDATE songs
                SET play_count = play_count + 1,
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'published'
                RETURNING play_count
            """,
            (music_id,)
        )

        row = cursor.fetchone()

        if not row:
            connection.rollback()

            return jsonify({
                "success": False,
                "error": "Song not found"
            }), 404

        connection.commit()

        return jsonify({
            "success": True,
            "music_id": music_id,
            "play_count": row[0]
        })

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@music_bp.post("/<int:music_id>/download")
@require_api_key
def download_music(music_id):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
                UPDATE songs
                SET download_count = download_count + 1,
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'published'
                  AND audio_url IS NOT NULL
                RETURNING
                    download_count,
                    audio_url
            """,
            (music_id,)
        )

        row = cursor.fetchone()

        if not row:
            connection.rollback()

            return jsonify({
                "success": False,
                "error": "Song not found or audio unavailable"
            }), 404

        connection.commit()

        return jsonify({
            "success": True,
            "music_id": music_id,
            "download_count": row[0],
            "audio_url": row[1]
        })

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass
