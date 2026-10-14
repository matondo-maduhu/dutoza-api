"""
Kikomo cha majaribio yasiyofaa ya login (kwa kila IP).

Kinahifadhiwa kwenye kumbukumbu ya process (kinatosha kwa seva moja).
Tunahesabu IP kutoka mwisho wa X-Forwarded-For, kwa sababu proxy ya Render
ndiyo inayoongeza IP halisi mwishoni (ile ya mwanzo mteja anaweza kuighushi).

Kikomo ni cha IP tu (si cha username/email), ili mtu asiweze kumfungia
admin au developer nje kwa kukosea password yake kwa makusudi.
"""

import threading
import time
from collections import defaultdict, deque

from flask import request

WINDOW_SECONDS = 600          # dakika 10
_lock = threading.Lock()
_failures = defaultdict(deque)


def client_ip():
    parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]

    return parts[-1] if parts else (request.remote_addr or "unknown")


def _key(scope):
    return "%s:%s" % (scope, client_ip())


def _prune(bucket, now):
    while bucket and now - bucket[0] > WINDOW_SECONDS:
        bucket.popleft()


def seconds_locked(scope, limit):
    """Sekunde zilizobaki kabla ya kuruhusiwa tena (0 = ruhusa)."""
    now = time.monotonic()

    with _lock:
        bucket = _failures.get(_key(scope))

        if not bucket:
            return 0

        _prune(bucket, now)

        if len(bucket) < limit:
            return 0

        return max(1, int(WINDOW_SECONDS - (now - bucket[0])) + 1)


def record_failure(scope):
    now = time.monotonic()

    with _lock:
        bucket = _failures[_key(scope)]
        _prune(bucket, now)
        bucket.append(now)

        # Usiruhusu kumbukumbu ikue bila kikomo
        if len(_failures) > 10000:
            for key in [k for k, v in _failures.items() if not v]:
                _failures.pop(key, None)


def clear(scope):
    with _lock:
        _failures.pop(_key(scope), None)


def minutes_text(seconds):
    return max(1, (seconds + 59) // 60)
