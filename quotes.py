from flask import Blueprint, jsonify, request
from db import get_connection
from auth import require_api_key

quotes_bp = Blueprint("quotes", __name__)


@quotes_bp.get("/")
@require_api_key
def get_quotes():
    try:
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = request.args.get("per_page", 20, type=int)

        # Zuia request kuomba data nyingi sana kwa mara moja
        per_page = min(max(per_page, 1), 100)

        category = request.args.get("category", "").strip()
        search = request.args.get("q", "").strip()

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
                    "(q.text ILIKE %s OR q.author ILIKE %s)"
                )

                search_value = f"%{search}%"
                params.extend([
                    search_value,
                    search_value
                ])

            where_sql = " AND ".join(conditions)

            count_sql = f"""
                SELECT COUNT(*)
                FROM quotes q
                LEFT JOIN categories c
                    ON c.id = q.category_id
                WHERE {where_sql}
            """

            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0]

            data_sql = f"""
                SELECT
                    q.id,
                    q.text,
                    q.author,
                    c.name AS category,
                    c.slug AS category_slug,
                    q.language,
                    q.created_at
                FROM quotes q
                LEFT JOIN categories c
                    ON c.id = q.category_id
                WHERE {where_sql}
                ORDER BY q.id DESC
                LIMIT %s OFFSET %s
            """

            cursor.execute(
                data_sql,
                params + [per_page, offset]
            )

            rows = cursor.fetchall()

            data = []

            for row in rows:
                data.append({
                    "id": row[0],
                    "text": row[1],
                    "author": row[2],
                    "category": row[3],
                    "category_slug": row[4],
                    "language": row[5],
                    "created_at": row[6].isoformat()
                    if row[6] else None
                })

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
                """
                SELECT
                    q.id,
                    q.text,
                    q.author,
                    c.name AS category,
                    c.slug AS category_slug,
                    q.language,
                    q.created_at
                FROM quotes q
                LEFT JOIN categories c
                    ON c.id = q.category_id
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
                "data": {
                    "id": row[0],
                    "text": row[1],
                    "author": row[2],
                    "category": row[3],
                    "category_slug": row[4],
                    "language": row[5],
                    "created_at": row[6].isoformat()
                    if row[6] else None
                }
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
                SELECT id, name, slug
                FROM categories
                ORDER BY name ASC
                """
            )

            rows = cursor.fetchall()

            return jsonify({
                "success": True,
                "data": [
                    {
                        "id": row[0],
                        "name": row[1],
                        "slug": row[2]
                    }
                    for row in rows
                ]
            })

        finally:
            connection.close()

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500
