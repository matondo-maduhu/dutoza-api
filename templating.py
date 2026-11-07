"""
Vifaa vya templates vinavyotumiwa na sehemu zote (users, developers, admin).

- asset("css/x.css")  -> "/static/css/x.css?v=<muda wa faili>".
  Toleo linabadilika faili ikibadilika, kwa hiyo browser inaweza kuhifadhi faili
  kwa muda mrefu (angalia perf.init_static_cache) na bado ipate sasisho mara moja.
- fmt_dt              -> filter ya kupanga tarehe kwenye templates.
"""

import os
from datetime import datetime

from flask import url_for

_versions = {}


def asset(filename):
    app_static = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    version = _versions.get(filename)

    if version is None:
        try:
            version = int(os.path.getmtime(os.path.join(app_static, filename)))
        except OSError:
            version = 0

        _versions[filename] = version

    return url_for("static", filename=filename, v=version)


def fmt_dt(value, fmt="%d %b %Y, %H:%M"):
    if not value:
        return "-"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace(" ", "T")[:19])
        except ValueError:
            return value

    try:
        return value.strftime(fmt)
    except Exception:
        return str(value)


def init_templating(app):
    app.jinja_env.filters["fmt_dt"] = fmt_dt
    app.jinja_env.globals["asset"] = asset
