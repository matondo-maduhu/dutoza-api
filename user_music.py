import os
import re
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template, session

from db import get_connection
from storage import upload_file


user_music_bp = Blueprint("user_music", __name__)


ALLOWED_AUDIO_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "aac",
    "ogg",
    "flac",
    "webm"
}

ALLOWED_IMAGE_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


def allowed_extension(filename, allowed):
    if not filename or "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed


def make_slug(title):
    value = (title or "").strip().lower()

    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value)
    value = value.strip("-")

    if not value:
        value = "music"

    return value


def unique_song_slug(connection, title):
    base_slug = make_slug(title)
    slug = base_slug
    counter = 2

    while True:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT id FROM songs WHERE slug = %s LIMIT 1",
                (slug,)
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

        if not row:
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


def get_current_user_id():
    user_id = session.get("user_id")

    if not user_id:
        return None

    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


@user_music_bp.get("/music/composer")
def music_composer():
    user_id = get_current_user_id()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401

    return render_template("users/music_composer.html")


@user_music_bp.post("/api/user/music")
def create_music_post():

    user_id = get_current_user_id()

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401


    audio = request.files.get("audio")
    cover = request.files.get("cover")

    title = (request.form.get("title") or "").strip()
    artist_name = (request.form.get("artist") or "").strip()
    album_title = (request.form.get("album") or "").strip()
    genre = (request.form.get("genre") or "").strip()
    language = (request.form.get("language") or "sw").strip()
    release_date = (request.form.get("release_date") or "").strip()
    description = (request.form.get("description") or "").strip()
    lyrics = (request.form.get("lyrics") or "").strip()


    if not audio or not audio.filename:
        return jsonify({
            "success": False,
            "message": "Chagua audio ya wimbo."
        }), 400


    if not title:
        return jsonify({
            "success": False,
            "message": "Jina la wimbo linahitajika."
        }), 400


    if not allowed_extension(
        audio.filename,
        ALLOWED_AUDIO_EXTENSIONS
    ):
        return jsonify({
            "success": False,
            "message": "Aina ya audio haikubaliki."
        }), 400


    if cover and cover.filename:
        if not allowed_extension(
            cover.filename,
            ALLOWED_IMAGE_EXTENSIONS
        ):
            return jsonify({
                "success": False,
                "message": "Aina ya cover haikubaliki."
            }), 400


    connection = None

    try:

        connection = get_connection()


        # -------------------------------------------------
        # VERIFY USER
        # -------------------------------------------------

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT id, full_name, username, status
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,)
            )

            user = cursor.fetchone()

        finally:
            cursor.close()


        if not user:
            return jsonify({
                "success": False,
                "message": "User account not found."
            }), 404


        if user[3] != "active":
            return jsonify({
                "success": False,
                "message": "Your account is not active."
            }), 403


        # -------------------------------------------------
        # OPTIONAL ARTIST
        # -------------------------------------------------

        artist_id = None

        if artist_name:

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    SELECT id
                    FROM artists
                    WHERE LOWER(name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (artist_name,)
                )

                artist = cursor.fetchone()

            finally:
                cursor.close()


            if artist:
                artist_id = artist[0]

            else:

                artist_slug = make_slug(artist_name)

                cursor = connection.cursor()

                try:

                    cursor.execute(
                        """
                        SELECT id
                        FROM artists
                        WHERE slug = %s
                        LIMIT 1
                        """,
                        (artist_slug,)
                    )

                    existing_artist = cursor.fetchone()

                    if existing_artist:
                        artist_id = existing_artist[0]

                    else:

                        cursor.execute(
                            """
                            INSERT INTO artists
                            (
                                name,
                                slug,
                                language,
                                status,
                                created_at,
                                updated_at
                            )
                            VALUES
                            (
                                %s,
                                %s,
                                %s,
                                'published',
                                NOW(),
                                NOW()
                            )
                            RETURNING id
                            """,
                            (
                                artist_name,
                                artist_slug,
                                language
                            )
                        )

                        new_artist = cursor.fetchone()

                        if new_artist:
                            artist_id = new_artist[0]

                finally:
                    cursor.close()


        # -------------------------------------------------
        # OPTIONAL ALBUM
        # -------------------------------------------------

        album_id = None

        if album_title:

            if artist_id:

                cursor = connection.cursor()

                try:
                    cursor.execute(
                        """
                        SELECT id
                        FROM albums
                        WHERE LOWER(title) = LOWER(%s)
                          AND artist_id = %s
                        LIMIT 1
                        """,
                        (
                            album_title,
                            artist_id
                        )
                    )

                    album = cursor.fetchone()

                finally:
                    cursor.close()


                if album:
                    album_id = album[0]

                else:

                    album_slug = make_slug(album_title)

                    cursor = connection.cursor()

                    try:

                        cursor.execute(
                            """
                            SELECT id
                            FROM albums
                            WHERE slug = %s
                            LIMIT 1
                            """,
                            (album_slug,)
                        )

                        existing_album = cursor.fetchone()

                        if existing_album:
                            album_id = existing_album[0]

                        else:

                            cursor.execute(
                                """
                                INSERT INTO albums
                                (
                                    artist_id,
                                    title,
                                    slug,
                                    language,
                                    status,
                                    created_at,
                                    updated_at
                                )
                                VALUES
                                (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    'published',
                                    NOW(),
                                    NOW()
                                )
                                RETURNING id
                                """,
                                (
                                    artist_id,
                                    album_title,
                                    album_slug,
                                    language
                                )
                            )

                            new_album = cursor.fetchone()

                            if new_album:
                                album_id = new_album[0]

                    finally:
                        cursor.close()


        # -------------------------------------------------
        # UPLOAD AUDIO TO R2
        # -------------------------------------------------

        audio_url = upload_file(
            audio,
            "music/audio"
        )


        # -------------------------------------------------
        # UPLOAD COVER TO R2
        # -------------------------------------------------

        cover_url = None

        if cover and cover.filename:

            cover_url = upload_file(
                cover,
                "music/covers"
            )


        # -------------------------------------------------
        # DURATION
        # -------------------------------------------------

        duration_seconds = None


        # -------------------------------------------------
        # RELEASE DATE
        # -------------------------------------------------

        parsed_release_date = None

        if release_date:

            try:
                parsed_release_date = datetime.strptime(
                    release_date,
                    "%Y-%m-%d"
                ).date()

            except ValueError:
                parsed_release_date = None


        # -------------------------------------------------
        # UNIQUE SONG SLUG
        # -------------------------------------------------

        slug = unique_song_slug(
            connection,
            title
        )


        # -------------------------------------------------
        # INSERT SONG
        # -------------------------------------------------

        cursor = connection.cursor()

        try:

            cursor.execute(
                """
                INSERT INTO songs
                (
                    user_id,
                    artist_id,
                    album_id,
                    title,
                    slug,
                    description,
                    lyrics,
                    audio_url,
                    cover_url,
                    duration_seconds,
                    genre,
                    language,
                    release_date,
                    status,
                    play_count,
                    download_count,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'published',
                    0,
                    0,
                    NOW(),
                    NOW()
                )
                RETURNING id
                """,
                (
                    user_id,
                    artist_id,
                    album_id,
                    title,
                    slug,
                    description or None,
                    lyrics or None,
                    audio_url,
                    cover_url,
                    duration_seconds,
                    genre or None,
                    language or "sw",
                    parsed_release_date
                )
            )

            song = cursor.fetchone()

        finally:
            cursor.close()


        if not song:
            raise RuntimeError(
                "Song could not be created."
            )


        song_id = song[0]

        connection.commit()


        return jsonify({
            "success": True,
            "message": "Wimbo umetumwa na umechapishwa na umeongezwa kwenye Feed.",
            "song": {
                "id": song_id,
                "title": title,
                "slug": slug,
                "status": "pending",
                "audio_url": audio_url,
                "cover_url": cover_url
            }
        }), 201


    except Exception as error:

        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        return jsonify({
            "success": False,
            "message": "Imeshindikana kutuma wimbo.",
            "error": str(error)
        }), 500


    finally:

        if connection:
            try:
                connection.close()
            except Exception:
                pass


@user_music_bp.delete("/api/user/music/<int:song_id>")
@user_music_bp.post("/api/user/music/<int:song_id>/delete")
def delete_music(song_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT user_id FROM songs WHERE id = %s LIMIT 1",
            (song_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Song not found"}), 404
        if int(row[0] or 0) != int(user_id):
            return jsonify({"success": False, "message": "Forbidden"}), 403

        cursor.execute("DELETE FROM songs WHERE id = %s", (song_id,))
        connection.commit()
        return jsonify({"success": True, "message": "Wimbo umefutwa"})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


@user_music_bp.post("/api/user/music/<int:song_id>/edit")
def edit_music(song_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or request.form.get("title") or "").strip()[:200]
    genre = (data.get("genre") or request.form.get("genre") or "").strip()[:80]
    description = (data.get("description") or request.form.get("description") or "").strip()[:1000]
    lyrics = (data.get("lyrics") or request.form.get("lyrics") or "").strip()[:8000]
    language = (data.get("language") or request.form.get("language") or "").strip()[:10]

    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT user_id FROM songs WHERE id = %s LIMIT 1",
            (song_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Song not found"}), 404
        if int(row[0] or 0) != int(user_id):
            return jsonify({"success": False, "message": "Forbidden"}), 403

        sets = []
        params = []
        if title:
            sets.append("title = %s")
            params.append(title)
        if genre or genre == "":
            sets.append("genre = %s")
            params.append(genre or None)
        if description or description == "":
            sets.append("description = %s")
            params.append(description or None)
        if lyrics or lyrics == "":
            sets.append("lyrics = %s")
            params.append(lyrics or None)
        if language:
            sets.append("language = %s")
            params.append(language)
        sets.append("updated_at = NOW()")
        if not title and len(sets) == 1:
            return jsonify({"success": False, "message": "Hakuna mabadiliko"}), 400

        params.append(song_id)
        cursor.execute(
            f"UPDATE songs SET {', '.join(sets)} WHERE id = %s",
            params,
        )
        connection.commit()
        return jsonify({"success": True, "message": "Wimbo umesasishwa"})
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass
