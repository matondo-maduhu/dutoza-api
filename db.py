import os
import queue
import threading
import time
from urllib.parse import urlparse, unquote

import pg8000.dbapi
from dotenv import load_dotenv

load_dotenv()

POOL_SIZE = 5
MAX_CONNECTION_RETRIES = 2
RETRY_DELAY = 0.15

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


def _connection_is_alive(connection):
    """
    Health-check ya connection iliyokaa kwenye pool.
    """

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        return True

    except Exception:
        try:
            connection.close()
        except Exception:
            pass

        return False


class PooledConnection:
    def __init__(self, connection):
        self._connection = connection
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        """
        Rudisha connection kwenye pool.

        Muhimu:
        Hatufanyi SELECT 1 hapa kwa sababu hiyo ilikuwa
        inaongeza query ya ziada kwa kila request.
        """

        if self._returned:
            return

        self._returned = True

        try:
            try:
                self._connection.rollback()
            except Exception:
                pass

            _pool.put_nowait(self._connection)

        except queue.Full:
            try:
                self._connection.close()
            except Exception:
                pass

        except Exception:
            try:
                self._connection.close()
            except Exception:
                pass


def _initialize_pool():
    global _pool_initialized

    if _pool_initialized:
        return

    with _pool_lock:
        if _pool_initialized:
            return

        connection = _create_connection()
        _pool.put(connection)

        _pool_initialized = True


def get_connection():
    """
    Toa connection kutoka kwenye pool.
    Pooled connections zinathibitishwa kabla ya kutumika.
    """

    _initialize_pool()

    last_error = None

    for attempt in range(MAX_CONNECTION_RETRIES + 1):
        connection = None

        try:
            connection = _pool.get_nowait()

            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()

            return PooledConnection(connection)

        except queue.Empty:
            try:
                connection = _create_connection()
                return PooledConnection(connection)

            except Exception as error:
                last_error = error

                if attempt < MAX_CONNECTION_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue

                raise last_error

        except Exception:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

            try:
                connection = _create_connection()
                return PooledConnection(connection)

            except Exception as error:
                last_error = error

                if attempt < MAX_CONNECTION_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue

                raise last_error
