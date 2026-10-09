from flask import Blueprint, jsonify, request
from db import get_connection
from auth import require_api_key

quotes_bp = Blueprint("quotes", __name__)


def serialize_quote(row):
    """
    row order:
      0 q.id
      1 q.text
      2 q.author
      3 category name
      4 category slug
      5 q.language
      6 q.created_at
      7 q.user_id
      8 u.full_name
      9 u.username
     10 u.profile_image_url
     11 q.status (optional, may be absent on some queries)
    """
    created = row[6]
    user_id = row[7] if len(row) > 7 else None

    data = {
        "id": row[0],
        "text": row[1],
        "author": row[2],
        "category": row[3],
        "category_slug": row[4],
        "language": row[5],
        "created_at": created.isoformat() if created else None,
        "user_id": user_id,
        "source": "user" if user_id else "admin",
    }

    if user_id and len(row) > 9:
        data["user"] = {
            "id": user_id,
            "full_name": row[8],
            "username": row[9],
            "profile_image_url": row[10] if len(row) > 10 else None,
        }
    else:
        data["user"] = None

    return data


QUOTE_SELECT = """
    SELECT
        q.id,
        q.text,
        q.author,
        c.name AS category,
        c.slug AS category_slug,
        q.language,
        q.created_at,
        q.user_id,
        u.full_name,
        u.username,
        u.profile_image_url
    FROM quotes q
    LEFT JOIN categories c
        ON c.id = q.category_id
    LEFT JOIN users u
        ON u.id = q.user_id
"""


@quotes_bp.get("/")
@require_api_key
def get_quotes():
    try:
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = request.args.get("per_page", 20, type=int)
        per_page = min(max(per_page, 1), 100)

        category = request.args.get("category", "").strip()
        search = request.args.get("q", "").strip()
        language = request.args.get("language", "").strip()
        user_id = request.args.get("user_id", type=int)
        source = request.args.get("source", "").strip().lower()

        offset = (page - 1) * per_page

        connection = get_connection()

        try:
            cursor = connection.cursor()

            conditions = [
                "q.status = 'published'"
            ]
            params = []

            if category:
                conditions.append(
                    "LOWER(c.slug) = LOWER(%s)"
                )
                params.append(category)

            if search:
                conditions.append(
                    """
                    (
                        q.text ILIKE %s
                        OR q.author ILIKE %s
                        OR u.username ILIKE %s
                        OR u.full_name ILIKE %s
                    )
                    """
                )
                search_value = f"%{search}%"
                params.extend([
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                ])

            if language:
                conditions.append(
                    "LOWER(q.language) = LOWER(%s)"
                )
                params.append(language)

            if user_id:
                conditions.append("q.user_id = %s")
                params.append(user_id)

            if source == "user":
                conditions.append("q.user_id IS NOT NULL")
            elif source == "admin":
                conditions.append("q.user_id IS NULL")

            where_sql = " AND ".join(conditions)

            count_sql = f"""
                SELECT COUNT(*)
                FROM quotes q
                LEFT JOIN categories c
                    ON c.id = q.category_id
                LEFT JOIN users u
                    ON u.id = q.user_id
                WHERE {where_sql}
            """

            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0]

            data_sql = f"""
                {QUOTE_SELECT}
                WHERE {where_sql}
                ORDER BY q.id DESC
                LIMIT %s OFFSET %s
            """

            cursor.execute(
                data_sql,
                params + [per_page, offset]
            )

            rows = cursor.fetchall()
            data = [serialize_quote(row) for row in rows]

            return jsonify({
                "success": True,
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (
                    (total + per_page - 1) // per_page
                    if total else 0
                ),
                "data": data
            })

        finally:
            connection.close()

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@quotes_bp.get("/<int:quote_id>")
@require_api_key
def get_quote_by_id(quote_id):
    try:
        connection = get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                f"""
                {QUOTE_SELECT}
                WHERE q.id = %s
                  AND q.status = 'published'
                """,
                (quote_id,)
            )

            row = cursor.fetchone()

            if not row:
                return jsonify({
                    "success": False,
                    "error": "Quote not found"
                }), 404

            return jsonify({
                "success": True,
                "data": serialize_quote(row)
            })

        finally:
            connection.close()

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@quotes_bp.get("/categories")
@require_api_key
def get_categories():
    try:
        connection = get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    slug
                FROM categories
                ORDER BY name ASC
                """
            )

            rows = cursor.fetchall()

            data = [
                {
                    "id": row[0],
                    "name": row[1],
                    "slug": row[2]
                }
                for row in rows
            ]

            return jsonify({
                "success": True,
                "data": data
            })

        finally:
            connection.close()

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500
