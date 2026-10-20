import os

from dotenv import load_dotenv

# Load .env BEFORE importing modules
load_dotenv()

from flask import Flask, jsonify, render_template, session
from music import music_bp
from quotes import quotes_bp
from admin import admin_bp
from developers import developers_bp
from user_auth import user_auth_bp
from user_feed import user_feed_bp
from user_music import user_music_bp
from schema import ensure_schema
from perf import init_compression
from guard import init_user_guard
from admin_panel import panel_bp
from pwa import pwa_bp
from security import init_security
from errors import init_errors

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "change-this-secret-in-production"
)

# Ulinzi lazima uanze KWANZA (ukaguzi wa chanzo cha ombi unatangulia kila kitu)
init_security(app)
init_compression(app)
init_user_guard(app)
init_errors(app)


# API
app.register_blueprint(
    music_bp,
    url_prefix="/api/music"
)

app.register_blueprint(
    quotes_bp,
    url_prefix="/api/quotes"
)


# Admin
app.register_blueprint(admin_bp)
app.register_blueprint(panel_bp)
app.register_blueprint(pwa_bp)
app.register_blueprint(developers_bp)
app.register_blueprint(user_auth_bp)
app.register_blueprint(user_feed_bp)
app.register_blueprint(user_music_bp)

# Tengeneza tables/indexes MARA MOJA wakati app inaanza.
# Kama DB haipatikani sasa, app bado inaanza; schema itajaribiwa tena
# mara ya kwanza request inapohitaji (ensure_schema ni salama kuitwa tena).
try:
    ensure_schema()
except Exception as error:
    print(f"[startup] schema haikukamilika: {error}")


@app.get("/developers")
def developers():
    return render_template(
        "developers/index.html",
        developer_logged_in=bool(session.get("developer_id")),
        nav_active="docs"
    )

@app.get("/")
def home():
    return render_template("home.html")


@app.get("/api")
def api_info():
    return jsonify({
        "name": "Mercfy API",
        "version": "1.0.0",
        "status": "online",
        "services": [
            "music",
            "quotes"
        ]
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.getenv("FLASK_DEBUG", "0") == "1"
    )
