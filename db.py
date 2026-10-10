import os
import queue
import threading
import time
from urllib.parse import urlparse, unquote

import pg8000.dbapi
from dotenv import load_dotenv

load_dotenv()

# Ukubwa wa pool (unaweza kubadilisha kupitia .env: DB_POOL_SIZE=10)
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_CONNECTION_RETRIES = 2
RETRY_DELAY = 0.15

# Connection iliyokaa bila kutumika zaidi ya sekunde hizi
# ndiyo tu inayofanyiwa health-check (SELECT 1). Zilizotumika hivi karibuni
# zinatumika moja kwa moja, hivyo tunaokoa round-trip kwa kila request.
IDLE_CHECK_SECONDS = float(os.getenv("DB_IDLE_CHECK_SECONDS", "20"))

# Pool inahifadhi tuple: (connection, wakati_ilipoachwa)
_pool = queue.Queue(maxsize=POOL_SIZE)
_pool_lock = threading.Lock()
_pool_initialized = False


def get_database_url():
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL haijawekwa.")

    return url


def _create_connection():
    url = get_database_url()
    parsed = urlparse(url)

    if not parsed.hostname:
        raise RuntimeError("DATABASE_URL si sahihi.")

    return pg8000.dbapi.connect(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        ssl_context=True,
    )


def _safe_close(connection):
    try:
        connection.close()
    except Exception:
        pass


def _connection_is_alive(connection):
    """Health-check ya connection iliyokaa muda mrefu kwenye pool."""
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        connection.rollback()
        return True
    except Exception:
        _safe_close(connection)
        return False


class PooledConnection:
    def __init__(self, connection):
        self._connection = connection
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        """Rudisha connection kwenye pool (haifungi connection halisi)."""
        if self._returned:
            return

        self._returned = True

        try:
            try:
                self._connection.rollback()
            except Exception:
                # Connection imevunjika - usiirudishe kwenye pool.
                _safe_close(self._connection)
                return

            _pool.put_nowait((self._connection, time.monotonic()))

        except queue.Full:
            _safe_close(self._connection)

        except Exception:
            _safe_close(self._connection)


def _initialize_pool():
    global _pool_initialized

    if _pool_initialized:
        return

    with _pool_lock:
        if _pool_initialized:
            return

        connection = _create_connection()
        _pool.put((connection, time.monotonic()))

        _pool_initialized = True


def get_connection():
    """
    Toa connection kutoka kwenye pool.
    Health-check hufanyika tu kama connection imekaa idle muda mrefu.
    """

    _initialize_pool()

    last_error = None

    for attempt in range(MAX_CONNECTION_RETRIES + 1):
        # 1) Jaribu kutumia connection iliyopo kwenye pool
        try:
            connection, released_at = _pool.get_nowait()
        except queue.Empty:
            connection = None

        if connection is not None:
            idle_for = time.monotonic() - released_at

            if idle_for < IDLE_CHECK_SECONDS or _connection_is_alive(connection):
                return PooledConnection(connection)

            # Connection mfu - endelea kutengeneza mpya hapa chini

        # 2) Hakuna connection nzuri kwenye pool - tengeneza mpya
        try:
            return PooledConnection(_create_connection())

        except Exception as error:
            last_error = error

            if attempt < MAX_CONNECTION_RETRIES:
                time.sleep(RETRY_DELAY)
                continue

            raise last_error
