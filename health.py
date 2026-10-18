"""
Ukaguzi wa mfumo (self-test).

Unaendesha kurasa na API halisi za app (maombi ya GET tu, hayabadilishi data)
kama mtumiaji, developer na admin, dhidi ya database halisi, na kuripoti
kipi kinafanya kazi na kipi kinashindwa pamoja na sababu.

Sababu ya hitilafu inakamatwa kutoka kwenye log za seva kwa wakati wa ombi,
kwa hiyo unaiona hata kama mteja anapata ujumbe wa jumla tu.
"""

import logging
import os
import re
import time
import traceback
from datetime import datetime, timezone
from html import unescape

from db import get_connection
from security import secret_key_is_weak

OK, WARN, FAIL, SKIP = "OK", "ONYO", "KOSA", "RUKA"
SLOW_MS = 1500
SLOW_DB_MS = 300

# Seva nyingi huua ombi linalozidi sekunde ~30. Tunasimama mapema kuliko hapo.
TIME_BUDGET_SECONDS = 20

GROUPS = ["Mazingira", "Mtumiaji", "Developer", "Admin", "Umma"]

# (kundi, jina, njia)
USER_PROBES = [
    ("Mtumiaji", "Feed (ukurasa)", "/feed"),
    ("Mtumiaji", "Feed API (posts 5)", "/api/user/posts?limit=5"),
    ("Mtumiaji", "Feed API (ukurasa unaofuata)", "/api/user/posts?limit=5&before=2099-01-01T00:00:00%2B00:00"),
    ("Mtumiaji", "Search (ukurasa)", "/search"),
    ("Mtumiaji", "Search API", "/api/user/search?q=a"),
    ("Mtumiaji", "Profile (ukurasa)", "/profile"),
    ("Mtumiaji", "Profile posts API", "/api/user/profile/posts"),
    ("Mtumiaji", "Settings", "/settings"),
    ("Mtumiaji", "Notifications (idadi)", "/api/user/notifications/unread-count"),
    ("Mtumiaji", "Notifications (orodha)", "/api/user/notifications"),
]

DEVELOPER_PROBES = [
    ("Developer", "Dashboard", "/developers/dashboard"),
    ("Developer", "API Keys", "/developers/keys"),
    ("Developer", "Profile", "/developers/profile"),
    ("Developer", "Settings", "/developers/settings"),
]

ADMIN_PROBES = [
    ("Admin", "Muhtasari (takwimu + chati)", "/admin/overview"),
    ("Admin", "Users", "/admin/users"),
    ("Admin", "Users (tafuta)", "/admin/users?q=a"),
    ("Admin", "Maudhui: quotes", "/admin/content?type=quote"),
    ("Admin", "Maudhui: quotes (tafuta)", "/admin/content?type=quote&q=a"),
    ("Admin", "Maudhui: muziki", "/admin/content?type=music"),
    ("Admin", "Maudhui: posts", "/admin/content?type=post"),
    ("Admin", "Reports", "/admin/reports"),
    ("Admin", "Developers", "/admin/developers"),
    ("Admin", "Developers (tafuta)", "/admin/developers?q=a"),
    ("Admin", "Maombi ya keys", "/admin/key-requests"),
    ("Admin", "Quotes", "/admin/quotes"),
    ("Admin", "Schema status", "/admin/schema-status"),
    ("Admin", "Muziki (ukurasa wa zamani)", "/admin/music"),
    ("Admin", "API Keys (ukurasa wa zamani)", "/admin/api-keys"),
]

PUBLIC_PROBES = [
    ("Umma", "Docs za API", "/developers"),
    ("Umma", "Manifest ya PWA", "/manifest.webmanifest"),
    ("Umma", "Ukurasa wa offline", "/offline"),
    ("Umma", "Login ya mtumiaji", "/login"),
    ("Umma", "Login ya developer", "/developers/login"),
]


class _Capture(logging.Handler):
    """Hukusanya makosa yaliyoandikwa kwenye log wakati wa ombi moja."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.items = []

    def emit(self, record):
        text = record.getMessage()

        if record.exc_info and record.exc_info[1] is not None:
            last = "".join(traceback.format_exception_only(*record.exc_info[:2])).strip()
            text = "%s | %s" % (text, last) if last not in text else text

        self.items.append(text)


def _short(text, limit=320):
    text = re.sub(r"\s+", " ", text or "").strip()

    return text if len(text) <= limit else text[: limit - 1] + "…"


def _flash_errors(html):
    found = re.findall(r'class="flash error"[^>]*>(.*?)</div>', html or "", flags=re.S)

    return [_short(unescape(re.sub(r"<[^>]+>", " ", item))) for item in found]


def _first_id(sql_variants):
    """Rudisha id ya kwanza kutoka kwenye query za chaguo (ya kwanza inayofanya kazi)."""
    for sql in sql_variants:
        connection = None

        try:
            connection = get_connection()
            cursor = connection.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            cursor.close()

            return row[0] if row else None

        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass

        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

    return None


def _probe(app, role, session_values, group, label, path):
    capture = _Capture()
    loggers = [logging.getLogger("mercfy"), app.logger]

    for lg in loggers:
        lg.addHandler(capture)

    started = time.perf_counter()
    status = None
    body = ""
    content_type = ""
    location = ""
    problem = None

    try:
        client = app.test_client()

        with client.session_transaction() as sess:
            for key, value in session_values.items():
                sess[key] = value

        response = client.get(path)
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        location = response.headers.get("Location", "")
        body = response.get_data(as_text=True)

    except Exception as error:                      # kosa ambalo hata Flask halikulishika
        problem = "%s: %s" % (type(error).__name__, error)

    finally:
        for lg in loggers:
            lg.removeHandler(capture)

    elapsed = int((time.perf_counter() - started) * 1000)
    details = list(capture.items)
    verdict = OK

    if problem:
        verdict = FAIL
        details.insert(0, problem)

    elif status is None or status >= 400:
        verdict = FAIL

    elif 300 <= status < 400:
        verdict = FAIL
        details.append("Imeelekezwa upya kwenda %s (huenda session haikukubaliwa)" % (location or "ukurasa mwingine"))

    else:
        if "json" in content_type:
            if '"success":false' in body.replace(" ", "").lower():
                verdict = FAIL
        else:
            errors = _flash_errors(body)

            if errors:
                verdict = FAIL
                details.extend(errors)

        if details and verdict == OK:
            verdict = WARN

    if verdict == OK and elapsed > SLOW_MS:
        verdict = WARN
        details.append("Polepole: %d ms" % elapsed)

    if verdict == FAIL and not details:
        details.append("HTTP %s bila maelezo kwenye log" % status)

    return {
        "group": group,
        "label": label,
        "path": path,
        "role": role,
        "status": status,
        "ms": elapsed,
        "verdict": verdict,
        "detail": _short(" || ".join(dict.fromkeys(details)), 420),
    }


def _skipped(group, label, path, reason):
    return {
        "group": group, "label": label, "path": path, "role": "-",
        "status": None, "ms": 0, "verdict": SKIP, "detail": reason,
    }


def _environment_checks(app):
    checks = []

    def add(label, verdict, detail):
        checks.append({"label": label, "verdict": verdict, "detail": detail})

    # --- database ---
    try:
        timings = []
        version = ""

        for _ in range(3):
            started = time.perf_counter()
            connection = get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()

            if not version:
                try:
                    cursor.execute("SELECT version()")
                    version = str(cursor.fetchone()[0])
                except Exception:
                    connection.rollback()

            cursor.close()
            connection.close()
            timings.append((time.perf_counter() - started) * 1000)

        avg = int(sum(timings) / len(timings))

        add(
            "Database: muunganisho",
            WARN if avg > SLOW_DB_MS else OK,
            "wastani %d ms kwa query moja%s%s" % (
                avg,
                " (polepole: DB iko mbali na seva?)" if avg > SLOW_DB_MS else "",
                (" · " + _short(version.split(" on ")[0], 60)) if version else "",
            ),
        )

        if version and "postgres" not in version.lower():
            add("Database: aina", WARN, "Si PostgreSQL: %s. SQL ya app imeandikwa kwa Postgres." % _short(version, 80))

    except Exception as error:
        add("Database: muunganisho", FAIL, _short("%s: %s" % (type(error).__name__, error)))

    # --- schema ---
    try:
        from schema import get_status

        status = get_status()

        if not status.get("db_ok"):
            add("Schema (tables/columns/indexes)", FAIL, _short(status.get("db_error") or "DB haipatikani"))
        else:
            def part(items):
                return sum(1 for item in items if item["exists"]), len(items)

            t_ok, t_all = part(status["tables"])
            c_ok, c_all = part(status["columns"])
            i_ok, i_all = part(status["indexes"])
            failed = status["last_run"]["failed"]
            complete = (t_ok == t_all and c_ok == c_all and i_ok == i_all and not failed)

            missing = [i["name"] for i in status["tables"] + status["columns"] + status["indexes"] if not i["exists"]]

            add(
                "Schema (tables/columns/indexes)",
                OK if complete else FAIL,
                "tables %d/%d · columns %d/%d · indexes %d/%d%s" % (
                    t_ok, t_all, c_ok, c_all, i_ok, i_all,
                    "" if complete else " · zinakosekana: " + _short(", ".join(missing[:8]), 200)
                    + (" · Fungua Schema Status na uendeshe schema upya" if missing else ""),
                ),
            )

    except Exception as error:
        add("Schema (tables/columns/indexes)", FAIL, _short("%s: %s" % (type(error).__name__, error)))

    # --- usalama na mipangilio ---
    weak = secret_key_is_weak(app)
    add("FLASK_SECRET_KEY", FAIL if weak else OK,
        "Haijawekwa au ni fupi/ya msingi: session zinaweza kughushiwa" if weak else "Imewekwa (ndefu ya kutosha)")

    secure = bool(app.config.get("SESSION_COOKIE_SECURE"))
    add("Cookies za session (Secure)", OK if secure else WARN,
        "Zinatumwa kwa HTTPS tu" if secure else "Secure imezimwa (FLASK_DEBUG=1 au SESSION_COOKIE_SECURE=0)")

    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    add("Debug mode", WARN if debug else OK, "IMEWASHWA - usiitumie production" if debug else "Imezimwa")

    add("Nenosiri la admin (ADMIN_PASSWORD_HASH)", OK if os.getenv("ADMIN_PASSWORD_HASH") else FAIL,
        "Imewekwa" if os.getenv("ADMIN_PASSWORD_HASH") else "Haijawekwa: admin hawezi kuingia")

    r2_keys = ["R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_PUBLIC_URL"]
    missing_r2 = [k for k in r2_keys if not os.getenv(k)]
    add("Hifadhi ya faili (Cloudflare R2)", OK if not missing_r2 else WARN,
        "Mipangilio yote imewekwa" if not missing_r2 else "Hazijawekwa: " + ", ".join(missing_r2) + " (upload ya picha/sauti haitafanya kazi)")

    return checks


def run_checks(app, group="all", budget=None):
    """
    group: "all" au moja ya GROUPS. budget: sekunde za juu za kukagua kurasa
    (zilizobaki zinaruka na kuashiria kuwa muda umeisha).
    """
    if group != "all" and group not in GROUPS:
        raise ValueError("Kundi si sahihi: %r" % (group,))

    budget = TIME_BUDGET_SECONDS if budget is None else budget
    started = time.perf_counter()
    out_of_time = {"hit": False}

    def wanted(name):
        return group == "all" or group == name

    environment = _environment_checks(app) if wanted("Mazingira") else []

    user_id = developer_id = None

    if wanted("Mtumiaji"):
        user_id = _first_id(["SELECT id FROM users WHERE status = 'active' ORDER BY id LIMIT 1"])

    if wanted("Developer"):
        developer_id = _first_id([
            "SELECT id FROM developers WHERE status = 'active' ORDER BY id LIMIT 1",
            "SELECT id FROM developers ORDER BY id LIMIT 1",
        ])

    def run(role, session_values, probe):
        grp, label, path = probe

        if time.perf_counter() - started > budget:
            out_of_time["hit"] = True
            return _skipped(grp, label, path,
                            "Muda umeisha (sekunde %d). Endesha kundi hili peke yake." % budget)

        return _probe(app, role, session_values, grp, label, path)

    probes = []

    if wanted("Mtumiaji"):
        for probe in USER_PROBES:
            if user_id is None:
                probes.append(_skipped(*probe, "Hakuna mtumiaji hai wa kujaribia"))
            else:
                probes.append(run("mtumiaji #%s" % user_id, {"user_id": user_id}, probe))

    if wanted("Developer"):
        for probe in DEVELOPER_PROBES:
            if developer_id is None:
                probes.append(_skipped(*probe, "Hakuna developer wa kujaribia"))
            else:
                probes.append(run("developer #%s" % developer_id, {"developer_id": developer_id}, probe))

    if wanted("Admin"):
        for probe in ADMIN_PROBES:
            probes.append(run("admin", {"admin_logged_in": True}, probe))

    if wanted("Umma"):
        for probe in PUBLIC_PROBES:
            probes.append(run("mgeni", {}, probe))

    everything = [p["verdict"] for p in probes] + [c["verdict"] for c in environment]
    summary = {v: everything.count(v) for v in (OK, WARN, FAIL, SKIP)}

    return {
        "at": datetime.now(timezone.utc),
        "group": group,
        "partial": out_of_time["hit"],
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "environment": environment,
        "probes": probes,
        "summary": summary,
        "report": build_report(environment, probes, summary),
    }


def build_report(environment, probes, summary):
    lines = [
        "UKAGUZI WA MFUMO · " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "Jumla: OK %d · ONYO %d · KOSA %d · RUKA %d" % (summary[OK], summary[WARN], summary[FAIL], summary[SKIP]),
        "",
        "MAZINGIRA",
    ]

    for item in environment:
        lines.append("[%s] %s - %s" % (item["verdict"], item["label"], item["detail"]))

    lines += ["", "KURASA NA API"]

    for p in probes:
        lines.append("[%s] %s %s -> %s, %d ms%s" % (
            p["verdict"], p["role"], p["path"], p["status"] if p["status"] is not None else "-", p["ms"],
            (" - " + p["detail"]) if p["detail"] else "",
        ))

    return "\n".join(lines)
