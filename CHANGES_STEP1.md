# Hatua ya 1 - Speed (mabadiliko)

## Faili mpya
- `schema.py`  : tables + indexes, zinaendeshwa MARA MOJA wakati app inaanza.
- `perf.py`    : gzip compression (bila dependency mpya).

## Ukurasa mpya wa admin: /admin/schema-status
- `templates/admin/schema_status.html` (mpya)
- `admin.py`: routes 2 mpya (GET /admin/schema-status, POST /admin/schema-status/run)
- `templates/admin/dashboard.html`: kiungo kipya "Schema Status"
- `schema.py`: inarekodi makosa na ina `get_status()` (usomaji tu)

## Faili zilizobadilika
- `db.py`          : pool ya 10 (DB_POOL_SIZE), SELECT 1 inafanyika tu kama connection imekaa idle >20s.
- `user_feed.py`   : engagement kwa query 1 (engagement_batch); feed/profile/search hazina N+1 tena;
                     `ensure_*_tables` hazifanyi DDL kila request; feed inapokea ?limit=&before= (hiari).
- `developers.py`  : `ensure_developers_table` inatumia schema.py.
- `app.py`         : inaendesha schema mara moja, gzip, debug kutoka FLASK_DEBUG (default: zima).

## Hayakubadilika
- URL zote, na funguo zote za JSON. Feed imeongezewa `has_more` na `next_before` tu.
- Hakuna column wala table iliyofutwa au kubadilishwa jina. requirements.txt ni ile ile.

## .env (hiari)
DB_POOL_SIZE=10
FLASK_DEBUG=1      # local development tu

## Kurudi nyuma
Rudisha faili 5 za juu kutoka zip ya awali na ufute `schema.py` na `perf.py`.
Indexes zilizotengenezwa hazidhuru (unaweza kuzifuta kwa DROP INDEX IF EXISTS idx_...).
