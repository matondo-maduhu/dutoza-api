"""
Makosa salama kwa mteja.

Hitilafu ya ndani (mfano maelezo ya database) HAIPASWI kutumwa kwa mtumiaji
wala kwa developers: inaweza kufichua majina ya tables, queries au mpangilio
wa mfumo. Tunaiandika kwenye log ya seva na kumpa mteja ujumbe wa jumla.
"""

import logging

log = logging.getLogger("incredibles")

GENERIC_MESSAGE = "Hitilafu ya ndani ya seva. Jaribu tena baadaye."


def public_error(error, message=GENERIC_MESSAGE):
    """Andika hitilafu kamili kwenye log; rudisha ujumbe wa jumla wa kumpa mteja."""
    log.error(
        "Hitilafu ya ndani: %r",
        error,
        exc_info=error if isinstance(error, BaseException) else None,
    )

    return message
