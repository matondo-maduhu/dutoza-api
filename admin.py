import csv
import io
import os
import re
import traceback

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from werkzeug.security import check_password_hash

from db import get_connection
from storage import upload_file
from auth import generate_api_key, hash_api_key
from schema import get_status, ensure_schema


admin_bp = Blueprint("admin", __name__)


def admin_logged_in():
    return session.get("admin_logged_in") is True


def safe_close(connection):
    """
    Funga database connection bila kuruhusu
    error ya network wakati wa close kuvunja request.
    """
    if connection:
        try:
            connection.close()
        except Exception:
            pass


def slugify(value):
    value = value.strip().lower()

    value = re.sub(
        r"[^\w\s-]",
        "",
        value,
        flags=re.UNICODE
    )

    value = re.sub(
        r"[-\s]+",
        "-",
        value
    )

    return value.strip("-")


def get_categories():
    last_error = None

    for attempt in range(3):
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    id,
                    name,
                    slug
                FROM categories
                ORDER BY name ASC
            """)

            return cursor.fetchall()

        except Exception as error:
            last_error = error

        finally:
            safe_close(connection)

    raise last_error


def _after_post(default_endpoint="admin.admin_dashboard"):
    """Rudi kwenye ukurasa ulioombwa (next) kama ni wa ndani ya /admin."""
    target = request.form.get("next", "")

    if target.startswith("/admin") and not target.startswith("//"):
        return redirect(target)

    return redirect(url_for(default_endpoint))



@admin_bp.route(
    "/admin/login",
    methods=["GET", "POST"]
)
def admin_login():

    if admin_logged_in():
        return redirect(
            url_for("admin.admin_dashboard")
        )

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        admin_username = os.getenv(
            "ADMIN_USERNAME",
            "admin"
        )

        admin_password_hash = os.getenv(
            "ADMIN_PASSWORD_HASH",
            ""
        )

        if (
            username == admin_username
            and admin_password_hash
            and check_password_hash(
                admin_password_hash,
                password
            )
        ):
            session["admin_logged_in"] = True

            return redirect(
                url_for("admin.admin_dashboard")
            )

        flash(
            "Username au password si sahihi.",
            "error"
        )

    return render_template(
        "admin/login.html"
    )


@admin_bp.get("/admin")
def admin_dashboard():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    return redirect(url_for("panel.overview"))


@admin_bp.post("/admin/quotes/add")
def add_quote():

    if not admin_logged_in():
        return redirect(
            url_for("admin.admin_login")
        )

    text = request.form.get(
        "text",
        ""
    ).strip()

    author = request.form.get(
        "author",
        ""
    ).strip()

    category_id = request.form.get(
        "category_id",
        type=int
    )

    language = request.form.get(
        "language",
        "sw"
    ).strip().lower()

    if not text:
        flash(
            "Quote haiwezi kuwa tupu.",
            "error"
        )

        return _after_post()

    if language not in {"sw", "en"}:
        language = "sw"

    connection = None

    try:
        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO quotes (
                text,
                author,
                category_id,
                language,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'published'
            )
            ON CONFLICT DO NOTHING
        """, (
            text,
            author or None,
            category_id,
            language
        ))

        connection.commit()

        if cursor.rowcount:
            flash(
                "Quote imeongezwa.",
                "success"
            )
        else:
            flash(
                "Quote hii tayari ipo.",
                "error"
            )

    except Exception as error:

        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kuongeza quote: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return _after_post()


@admin_bp.post("/admin/categories/add")
def add_category():

    if not admin_logged_in():
        return redirect(
            url_for("admin.admin_login")
        )

    name = request.form.get(
        "name",
        ""
    ).strip()

    if not name:
        flash(
            "Jina la category linahitajika.",
            "error"
        )

        return _after_post()

    slug = slugify(name)

    if not slug:
        flash(
            "Jina la category si sahihi.",
            "error"
        )

        return _after_post()

    connection = None

    try:
        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO categories (
                name,
                slug
            )
            VALUES (
                %s,
                %s
            )
            ON CONFLICT (slug)
            DO NOTHING
        """, (
            name,
            slug
        ))

        connection.commit()

        if cursor.rowcount:
            flash(
                "Category imeongezwa.",
                "success"
            )
        else:
            flash(
                "Category hiyo tayari ipo.",
                "error"
            )

    except Exception as error:

        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kuongeza category: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return _after_post()


@admin_bp.route(
    "/admin/quotes/bulk-upload",
    methods=["GET", "POST"]
)
def bulk_upload():

    if not admin_logged_in():
        return redirect(
            url_for("admin.admin_login")
        )

    if request.method == "GET":
        return render_template(
            "admin/bulk_upload.html"
        )

    file = request.files.get(
        "csv_file"
    )

    if not file or not file.filename:
        flash(
            "Chagua CSV file kwanza.",
            "error"
        )

        return _after_post("admin.bulk_upload")

    if not file.filename.lower().endswith(
        ".csv"
    ):
        flash(
            "File lazima iwe CSV.",
            "error"
        )

        return _after_post("admin.bulk_upload")

    connection = None

    try:
        text_stream = io.TextIOWrapper(
            file.stream,
            encoding="utf-8-sig",
            newline=""
        )

        reader = csv.DictReader(
            text_stream
        )

        if not reader.fieldnames:
            raise ValueError(
                "CSV haina header."
            )

        headers = {
            header.strip().lower()
            for header in reader.fieldnames
            if header
        }

        required_headers = {
            "text",
            "author",
            "category",
            "language"
        }

        missing = (
            required_headers - headers
        )

        if missing:
            raise ValueError(
                "Columns zinazokosekana: "
                + ", ".join(sorted(missing))
            )

        connection = get_connection()

        cursor = connection.cursor()

        # --------------------------------
        # CATEGORY CACHE
        # --------------------------------

        category_cache = {}

        cursor.execute("""
            SELECT
                id,
                name,
                slug
            FROM categories
        """)

        for row in cursor.fetchall():

            category_id = row[0]

            category_name = (
                row[1].strip().lower()
            )

            category_slug = (
                row[2].strip().lower()
            )

            category_cache[
                category_name
            ] = category_id

            category_cache[
                category_slug
            ] = category_id

        # --------------------------------
        # COUNTERS
        # --------------------------------

        total = 0
        imported = 0
        skipped = 0
        invalid = 0

        # --------------------------------
        # BATCH SETTINGS
        # --------------------------------

        batch = []

        batch_size = 500

        # --------------------------------
        # BATCH INSERT
        # --------------------------------

        def process_batch(items):

            nonlocal imported
            nonlocal skipped

            if not items:
                return

            cursor.executemany("""
                INSERT INTO quotes (
                    text,
                    author,
                    category_id,
                    language,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'published'
                )
                ON CONFLICT DO NOTHING
            """, items)

            affected = cursor.rowcount

            if affected is None or affected < 0:
                affected = 0

            imported += affected

            skipped += (
                len(items) - affected
            )

            connection.commit()

        # --------------------------------
        # READ CSV
        # --------------------------------

        for csv_row in reader:

            total += 1

            text = (
                csv_row.get("text")
                or ""
            ).strip()

            author = (
                csv_row.get("author")
                or ""
            ).strip()

            category = (
                csv_row.get("category")
                or ""
            ).strip()

            language = (
                csv_row.get("language")
                or "sw"
            ).strip().lower()

            # --------------------------------
            # VALIDATION
            # --------------------------------

            if not text:
                invalid += 1
                continue

            if not category:
                invalid += 1
                continue

            if language not in {
                "sw",
                "en"
            }:
                language = "sw"

            # --------------------------------
            # FIND CATEGORY
            # --------------------------------

            category_key = category.lower()

            category_id = category_cache.get(
                category_key
            )

            # --------------------------------
            # CREATE CATEGORY IF NEEDED
            # --------------------------------

            if category_id is None:

                slug = slugify(category)

                cursor.execute("""
                    INSERT INTO categories (
                        name,
                        slug
                    )
                    VALUES (
                        %s,
                        %s
                    )
                    ON CONFLICT (slug)
                    DO NOTHING
                    RETURNING id
                """, (
                    category,
                    slug
                ))

                result = cursor.fetchone()

                if result:

                    category_id = result[0]

                else:

                    cursor.execute("""
                        SELECT id
                        FROM categories
                        WHERE slug = %s
                    """, (
                        slug,
                    ))

                    result = cursor.fetchone()

                    if not result:
                        raise RuntimeError(
                            "Imeshindikana kupata "
                            f"category: {category}"
                        )

                    category_id = result[0]

                category_cache[
                    category_key
                ] = category_id

                category_cache[
                    slug
                ] = category_id

                connection.commit()

            # --------------------------------
            # ADD TO BATCH
            # --------------------------------

            batch.append((
                text,
                author or None,
                category_id,
                language
            ))

            # --------------------------------
            # PROCESS EVERY 500 ROWS
            # --------------------------------

            if len(batch) >= batch_size:

                process_batch(batch)

                batch = []

        # --------------------------------
        # PROCESS REMAINING ROWS
        # --------------------------------

        process_batch(batch)

        connection.commit()

        flash(
            "CSV imekamilika. "
            f"Rows: {total}, "
            f"Imported: {imported}, "
            f"Skipped: {skipped}, "
            f"Invalid: {invalid}",
            "success"
        )

    except Exception as error:

        if connection:

            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"CSV upload imeshindikana: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return _after_post("admin.bulk_upload")


@admin_bp.get("/admin/logout")
def admin_logout():

    session.clear()

    return redirect(
        url_for("admin.admin_login")
    )
 
 
@admin_bp.get("/admin/music")
def music_admin():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                name,
                slug,
                country,
                language,
                status
            FROM artists
            ORDER BY id DESC
        """)
        artists = cursor.fetchall()

        cursor.execute("""
            SELECT
                al.id,
                al.title,
                al.slug,
                ar.name,
                al.release_date,
                al.status
            FROM albums al
            LEFT JOIN artists ar
                ON ar.id = al.artist_id
            ORDER BY al.id DESC
        """)
        albums = cursor.fetchall()

        cursor.execute("""
            SELECT
                s.id,
                s.title,
                ar.name,
                al.title,
                s.genre,
                s.language,
                s.status,
                s.audio_url
            FROM songs s
            LEFT JOIN artists ar
                ON ar.id = s.artist_id
            LEFT JOIN albums al
                ON al.id = s.album_id
            ORDER BY s.id DESC
        """)
        songs = cursor.fetchall()

        return render_template(
            "admin/music.html",
            artists=artists,
            albums=albums,
            songs=songs
        )

    except Exception as error:
        flash(
            f"Imeshindikana kupakia music manager: {error}",
            "error"
        )

        return render_template(
            "admin/music.html",
            artists=[],
            albums=[],
            songs=[]
        )

    finally:
        safe_close(connection)


@admin_bp.post("/admin/music/artists/add")
def add_artist():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    name = request.form.get("name", "").strip()
    bio = request.form.get("bio", "").strip()
    image_url = request.form.get("image_url", "").strip()
    country = request.form.get("country", "").strip()
    language = request.form.get("language", "sw").strip().lower()

    if not name:
        flash("Artist name inahitajika.", "error")
        return redirect(url_for("admin.music_admin"))

    if language not in {"sw", "en"}:
        language = "sw"

    slug = slugify(name)

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO artists (
                name,
                slug,
                bio,
                image_url,
                country,
                language,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'published'
            )
            ON CONFLICT (slug)
            DO NOTHING
        """, (
            name,
            slug,
            bio or None,
            image_url or None,
            country or None,
            language
        ))

        connection.commit()

        if cursor.rowcount:
            flash("Artist ameongezwa.", "success")
        else:
            flash("Artist huyo tayari yupo.", "error")

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kuongeza artist: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return redirect(url_for("admin.music_admin"))


@admin_bp.post("/admin/music/albums/add")
def add_album():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    title = request.form.get("title", "").strip()
    artist_id = request.form.get("artist_id", type=int)
    description = request.form.get("description", "").strip()
    cover_url = request.form.get("cover_url", "").strip()
    release_date = request.form.get("release_date", "").strip()
    language = request.form.get("language", "sw").strip().lower()

    if not title:
        flash("Album title inahitajika.", "error")
        return redirect(url_for("admin.music_admin"))

    if not artist_id:
        flash("Chagua artist wa album.", "error")
        return redirect(url_for("admin.music_admin"))

    if language not in {"sw", "en"}:
        language = "sw"

    slug = slugify(title)

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT id
            FROM artists
            WHERE id = %s
        """, (artist_id,))

        if not cursor.fetchone():
            flash("Artist huyo hayupo.", "error")
            return redirect(url_for("admin.music_admin"))

        cursor.execute("""
            INSERT INTO albums (
                artist_id,
                title,
                slug,
                description,
                cover_url,
                release_date,
                language,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                NULLIF(%s, '')::DATE,
                %s,
                'published'
            )
            ON CONFLICT (slug)
            DO NOTHING
        """, (
            artist_id,
            title,
            slug,
            description or None,
            cover_url or None,
            release_date,
            language
        ))

        connection.commit()

        if cursor.rowcount:
            flash("Album umeongezwa.", "success")
        else:
            flash("Album huo tayari upo.", "error")

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kuongeza album: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return redirect(url_for("admin.music_admin"))


@admin_bp.post("/admin/music/songs/add")
def add_song():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    title = request.form.get("title", "").strip()
    artist_id = request.form.get("artist_id", type=int)
    album_id = request.form.get("album_id", type=int)
    description = request.form.get("description", "").strip()
    lyrics = request.form.get("lyrics", "").strip()

    audio_url = request.form.get("audio_url", "").strip()
    cover_url = request.form.get("cover_url", "").strip()

    audio_file = request.files.get("audio_file")
    cover_file = request.files.get("cover_file")

    duration_seconds = request.form.get(
        "duration_seconds",
        type=int
    )

    track_number = request.form.get(
        "track_number",
        type=int
    )

    genre = request.form.get("genre", "").strip()
    language = request.form.get("language", "sw").strip().lower()
    release_date = request.form.get("release_date", "").strip()

    if not title:
        flash("Song title inahitajika.", "error")
        return redirect(url_for("admin.music_admin"))

    if language not in {"sw", "en"}:
        language = "sw"

    if duration_seconds is not None and duration_seconds < 0:
        flash("Duration haiwezi kuwa chini ya 0.", "error")
        return redirect(url_for("admin.music_admin"))

    if track_number is not None and track_number <= 0:
        flash("Track number lazima iwe zaidi ya 0.", "error")
        return redirect(url_for("admin.music_admin"))

    # Upload audio file kwenda R2 kama imechaguliwa
    if audio_file and audio_file.filename:
        try:
            audio_url = upload_file(
                audio_file,
                "music/audio"
            )
        except Exception as error:
            flash(
                f"Audio upload imeshindikana: {error}",
                "error"
            )
            return redirect(url_for("admin.music_admin"))

    # Upload cover image kwenda R2 kama imechaguliwa
    if cover_file and cover_file.filename:
        content_type = (
            cover_file.content_type or ""
        ).lower()

        if not content_type.startswith("image/"):
            flash(
                "Cover lazima iwe image.",
                "error"
            )
            return redirect(url_for("admin.music_admin"))

        try:
            cover_url = upload_file(
                cover_file,
                "music/covers"
            )
        except Exception as error:
            flash(
                f"Cover upload imeshindikana: {error}",
                "error"
            )
            return redirect(url_for("admin.music_admin"))

    slug = slugify(title)

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        if artist_id:
            cursor.execute("""
                SELECT id
                FROM artists
                WHERE id = %s
            """, (artist_id,))

            if not cursor.fetchone():
                flash("Artist huyo hayupo.", "error")
                return redirect(url_for("admin.music_admin"))

        if album_id:
            cursor.execute("""
                SELECT id
                FROM albums
                WHERE id = %s
            """, (album_id,))

            if not cursor.fetchone():
                flash("Album huo haupo.", "error")
                return redirect(url_for("admin.music_admin"))

        cursor.execute("""
            INSERT INTO songs (
                artist_id,
                album_id,
                title,
                slug,
                description,
                lyrics,
                audio_url,
                cover_url,
                duration_seconds,
                track_number,
                genre,
                language,
                release_date,
                status
            )
            VALUES (
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
                NULLIF(%s, '')::DATE,
                'published'
            )
            ON CONFLICT (slug)
            DO NOTHING
        """, (
            artist_id or None,
            album_id or None,
            title,
            slug,
            description or None,
            lyrics or None,
            audio_url or None,
            cover_url or None,
            duration_seconds,
            track_number,
            genre or None,
            language,
            release_date
        ))

        connection.commit()

        if cursor.rowcount:
            flash(
                "Song imeongezwa successfully.",
                "success"
            )
        else:
            flash(
                "Song hiyo tayari ipo.",
                "error"
            )

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        print("\n========== ADD SONG ERROR ==========")
        traceback.print_exc()
        print("====================================\n")

        flash(
            f"Imeshindikana kuongeza song: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return redirect(url_for("admin.music_admin"))

# ============================================================
# API KEYS MANAGER
# ============================================================

@admin_bp.get("/admin/api-keys")
def api_keys_admin():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                name,
                key_prefix,
                owner_name,
                owner_email,
                status,
                last_used_at,
                created_at
            FROM api_keys
            ORDER BY id DESC
        """)

        api_keys = cursor.fetchall()

    except Exception as error:
        flash(
            f"Imeshindikana kupakia API Keys: {error}",
            "error"
        )
        api_keys = []

    finally:
        safe_close(connection)

    return render_template(
        "admin/api_keys.html",
        api_keys=api_keys
    )


@admin_bp.post("/admin/api-keys/create")
def create_api_key():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    name = request.form.get("name", "").strip()
    owner_name = request.form.get("owner_name", "").strip()
    owner_email = request.form.get("owner_email", "").strip()

    if not name:
        flash("Jina la API Key linahitajika.", "error")
        return redirect(url_for("admin.api_keys_admin"))

    if owner_email and "@" not in owner_email:
        flash("Email ya developer si sahihi.", "error")
        return redirect(url_for("admin.api_keys_admin"))

    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    key_prefix = api_key[:16]

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO api_keys (
                name,
                key_hash,
                key_prefix,
                owner_name,
                owner_email,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                'active'
            )
            RETURNING id
        """, (
            name,
            key_hash,
            key_prefix,
            owner_name or None,
            owner_email or None
        ))

        key_id = cursor.fetchone()[0]

        connection.commit()

        flash(
            "API Key imetengenezwa. Ionyeshe developer sasa kwa sababu "
            "key kamili haitahifadhiwa kwenye database.",
            "success"
        )

        return render_template(
            "admin/api_keys.html",
            api_keys=[],
            newly_created_key=api_key,
            newly_created_key_id=key_id
        )

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kutengeneza API Key: {error}",
            "error"
        )

        return redirect(url_for("admin.api_keys_admin"))

    finally:
        safe_close(connection)


@admin_bp.post("/admin/api-keys/<int:key_id>/toggle")
def toggle_api_key(key_id):
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE api_keys
            SET status =
                CASE
                    WHEN status = 'active'
                    THEN 'inactive'
                    ELSE 'active'
                END
            WHERE id = %s
        """, (key_id,))

        if cursor.rowcount == 0:
            flash("API Key haijapatikana.", "error")
        else:
            connection.commit()
            flash("Status ya API Key imebadilishwa.", "success")

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kubadilisha API Key: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return redirect(url_for("admin.api_keys_admin"))


@admin_bp.post("/admin/api-keys/<int:key_id>/delete")
def delete_api_key(key_id):
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM api_keys
            WHERE id = %s
        """, (key_id,))

        if cursor.rowcount == 0:
            flash("API Key haijapatikana.", "error")
        else:
            connection.commit()
            flash("API Key imefutwa.", "success")

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        flash(
            f"Imeshindikana kufuta API Key: {error}",
            "error"
        )

    finally:
        safe_close(connection)

    return redirect(url_for("admin.api_keys_admin"))


@admin_bp.get("/admin/schema-status")
def schema_status():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    return render_template(
        "admin/schema_status.html",
        status=get_status(),
        active="schema"
    )


@admin_bp.post("/admin/schema-status/run")
def schema_status_run():
    if not admin_logged_in():
        return redirect(url_for("admin.admin_login"))

    try:
        ok = ensure_schema(force=True)

        if ok:
            flash("Schema imeendeshwa upya bila makosa.", "success")
        else:
            flash(
                "Schema imeendeshwa, lakini baadhi ya statements zimeshindwa. "
                "Angalia orodha ya makosa hapa chini.",
                "error"
            )

    except Exception as error:
        flash(f"Imeshindikana kuendesha schema: {error}", "error")

    return redirect(url_for("admin.schema_status"))
