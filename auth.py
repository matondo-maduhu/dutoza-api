import hashlib
import secrets
from functools import wraps
import datetime
import time

from flask import request, jsonify

from db import get_connection


DEFAULT_RATE_LIMIT = 100
RATE_LIMIT_WINDOW_SECONDS = 60


# ------------------------------------------------------------
# Scopes: key inaruhusiwa huduma gani (quotes / music)
# ------------------------------------------------------------
# Jina la blueprint -> scope inayohitajika. Blueprints zisizo hapa
# hazihitaji scope.
SCOPE_BY_BLUEPRINT = {
    "quotes": "quotes",
    "music": "music",
}

ALL_SCOPES = ("quotes", "music")
SCOPE_CACHE_SECONDS = 30

_scope_cache = {}  # key_id -> (expires_monotonic, frozenset(scopes))


def invalidate_key_scopes(key_id):
    """Futa cache ya scopes (admin akibadilisha scopes za key)."""
    try:
        _scope_cache.pop(int(key_id), None)
    except (TypeError, ValueError):
        pass


def parse_scopes(value):
    if not value:
        return frozenset(ALL_SCOPES)

    return frozenset(
        part.strip() for part in str(value).split(",") if part.strip()
    )


def key_has_scope(cursor, key_id, scope):
    """
    True kama key inaruhusiwa scope hii.
    Query hufanyika mara moja kila sekunde 30 kwa key. Kama column ya
    scopes haipo bado (schema haijaendeshwa), tabia ya zamani inabaki:
    key inaruhusiwa vyote.
    """
    now = time.monotonic()
    cached = _scope_cache.get(key_id)

    if cached and cached[0] > now:
        return scope in cached[1]

    try:
        cursor.execute(
            "SELECT scopes FROM api_keys WHERE id = %s",
            (key_id,)
        )
        row = cursor.fetchone()
        scopes = parse_scopes(row[0] if row else None)

    except Exception:
        # Transaction ya Postgres inaharibika baada ya kosa - irudishe
        try:
            cursor.connection.rollback()
        except Exception:
            pass

        return True

    if len(_scope_cache) > 5000:
        _scope_cache.clear()

    _scope_cache[key_id] = (now + SCOPE_CACHE_SECONDS, scopes)

    return scope in scopes


def generate_api_key():
    return "dutoza_" + secrets.token_urlsafe(32)


def hash_api_key(api_key):
    return hashlib.sha256(
        api_key.encode("utf-8")
    ).hexdigest()


def require_api_key(view_function):
    """
    API authentication + rate limiting.
    Uses one PostgreSQL statement for auth,
    rate-limit counting, and usage update.
    """

    @wraps(view_function)
    def wrapped(*args, **kwargs):

        authorization = request.headers.get(
            "Authorization",
            ""
        ).strip()

        if not authorization:
            return jsonify({
                "success": False,
                "error": "API key required",
                "message": (
                    "Tuma API key kupitia "
                    "Authorization: Bearer YOUR_API_KEY"
                )
            }), 401

        parts = authorization.split(None, 1)

        if len(parts) != 2:
            return jsonify({
                "success": False,
                "error": "Invalid authorization header",
                "message": (
                    "Format sahihi ni: "
                    "Authorization: Bearer YOUR_API_KEY"
                )
            }), 401

        scheme, api_key = parts

        if scheme.lower() != "bearer":
            return jsonify({
                "success": False,
                "error": "Invalid authorization scheme",
                "message": "Tumia Bearer authentication."
            }), 401

        api_key = api_key.strip()

        if not api_key:
            return jsonify({
                "success": False,
                "error": "API key required"
            }), 401

        key_hash = hash_api_key(api_key)

        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                WITH api AS (
                    SELECT
                        id,
                        name,
                        status,
                        COALESCE(
                            rate_limit,
                            %s
                        ) AS rate_limit
                    FROM api_keys
                    WHERE key_hash = %s
                    LIMIT 1
                ),

                rate AS (
                    INSERT INTO api_rate_limits (
                        api_key_id,
                        window_started_at,
                        request_count
                    )
                    SELECT
                        id,
                        NOW(),
                        1
                    FROM api

                    ON CONFLICT (api_key_id)
                    DO UPDATE SET
                        window_started_at =
                            CASE
                                WHEN api_rate_limits.window_started_at
                                     <= NOW() - INTERVAL '60 seconds'
                                THEN NOW()
                                ELSE api_rate_limits.window_started_at
                            END,

                        request_count =
                            CASE
                                WHEN api_rate_limits.window_started_at
                                     <= NOW() - INTERVAL '60 seconds'
                                THEN 1
                                ELSE api_rate_limits.request_count + 1
                            END

                    RETURNING
                        api_key_id,
                        window_started_at,
                        request_count
                ),

                valid AS (
                    SELECT
                        api.id,
                        api.name,
                        api.status,
                        api.rate_limit,
                        rate.window_started_at,
                        rate.request_count
                    FROM api
                    JOIN rate
                        ON rate.api_key_id = api.id
                ),

                usage AS (
                    UPDATE api_keys
                    SET
                        last_used_at = NOW(),
                        request_count = api_keys.request_count + 1
                    FROM valid
                    WHERE api_keys.id = valid.id
                      AND valid.status = 'active'
                      AND valid.request_count <= valid.rate_limit
                    RETURNING api_keys.id
                )

                SELECT
                    valid.id,
                    valid.name,
                    valid.status,
                    valid.rate_limit,
                    valid.window_started_at,
                    valid.request_count
                FROM valid
                """,
                (
                    DEFAULT_RATE_LIMIT,
                    key_hash
                )
            )

            row = cursor.fetchone()

            if not row:
                connection.rollback()

                return jsonify({
                    "success": False,
                    "error": "Invalid API key"
                }), 401

            key_id = row[0]
            key_name = row[1]
            status = row[2]
            rate_limit = row[3] or DEFAULT_RATE_LIMIT
            window_started_at = row[4]
            window_request_count = row[5]

            if status != "active":
                connection.rollback()

                messages = {
                    "pending": (
                        "API key hii inasubiri idhini ya administrator."
                    ),
                    "rejected": (
                        "Ombi la API key hii lilikataliwa."
                    ),
                    "revoked": (
                        "API key hii imefutwa."
                    ),
                }

                return jsonify({
                    "success": False,
                    "error": "API key inactive",
                    "message": messages.get(
                        status,
                        "API key hii imezimwa na administrator."
                    )
                }), 403

            required_scope = SCOPE_BY_BLUEPRINT.get(request.blueprint)

            if required_scope and not key_has_scope(
                cursor, key_id, required_scope
            ):
                connection.rollback()

                return jsonify({
                    "success": False,
                    "error": "Scope not allowed",
                    "message": (
                        "API key hii haina ruhusa ya huduma hii. "
                        f"Inahitaji ruhusa ya '{required_scope}'."
                    )
                }), 403

            if rate_limit < 1:
                rate_limit = DEFAULT_RATE_LIMIT

            now = datetime.datetime.now(
                datetime.timezone.utc
            )

            if window_started_at.tzinfo is None:
                window_started_at = (
                    window_started_at.replace(
                        tzinfo=datetime.timezone.utc
                    )
                )

            window_age = (
                now - window_started_at
            ).total_seconds()

            if window_request_count > rate_limit:

                retry_after = max(
                    1,
                    int(
                        RATE_LIMIT_WINDOW_SECONDS
                        - window_age
                    )
                )

                connection.rollback()

                response = jsonify({
                    "success": False,
                    "error": "Rate limit exceeded",
                    "message": (
                        "Umefikia kiwango cha requests "
                        "kinachoruhusiwa kwa dakika."
                    ),
                    "rate_limit": rate_limit,
                    "retry_after": retry_after
                })

                response.headers["Retry-After"] = str(
                    retry_after
                )

                return response, 429

            connection.commit()

            request.api_key_id = key_id
            request.api_key_name = key_name
            request.api_rate_limit = rate_limit

            request.api_rate_limit_remaining = max(
                0,
                rate_limit - window_request_count
            )

            response = view_function(
                *args,
                **kwargs
            )

            try:
                response.headers[
                    "X-RateLimit-Limit"
                ] = str(rate_limit)

                response.headers[
                    "X-RateLimit-Remaining"
                ] = str(
                    max(
                        0,
                        rate_limit - window_request_count
                    )
                )

                response.headers[
                    "X-RateLimit-Reset"
                ] = str(
                    max(
                        1,
                        int(
                            RATE_LIMIT_WINDOW_SECONDS
                            - window_age
                        )
                    )
                )

            except AttributeError:
                pass

            return response

        except Exception as error:

            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass

            print(
                "API authentication error:",
                repr(error)
            )

            return jsonify({
                "success": False,
                "error": "Authentication service error"
            }), 500

        finally:

            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

    return wrapped
