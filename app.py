import os

from dotenv import load_dotenv

# Load .env BEFORE importing modules
load_dotenv()

from flask import Flask, jsonify, render_template
from music import music_bp
from quotes import quotes_bp
from admin import admin_bp
from developers import developers_bp
from user_auth import user_auth_bp
from user_feed import user_feed_bp
from user_music import user_music_bp

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "change-this-secret-in-production"
)


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
app.register_blueprint(developers_bp)
app.register_blueprint(user_auth_bp)
app.register_blueprint(user_feed_bp)
app.register_blueprint(user_music_bp)

@app.get("/developers")
def developers():
    return render_template("developers/index.html")

@app.get("/")
def home():
    return render_template("home.html")


@app.get("/api")
def api_info():
    return jsonify({
        "name": "Dutoza API",
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
        debug=True
    )
