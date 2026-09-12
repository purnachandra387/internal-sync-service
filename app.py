"""
Internal Data Sync Service
---------------------------
A lightweight internal-style service that pulls data from an external
API (GitHub's public repo API) and keeps a local SQLite store in sync,
with basic health/status monitoring and error handling.

This mirrors a common "Application Engineering" pattern: integrating
a third-party/vendor system with an internal data store and exposing
that integration as a simple internal service.
"""

from flask import Flask, jsonify
import requests
import sqlite3
import datetime
import logging

app = Flask(__name__)

DB_PATH = "sync.db"
GITHUB_USERNAME = "purnachandra387"  # change to any public GitHub username
GITHUB_API_URL = f"https://api.github.com/users/{GITHUB_USERNAME}/repos"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync-service")


def init_db():
    """Create the repos table and a sync_log table if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            name TEXT PRIMARY KEY,
            stars INTEGER,
            language TEXT,
            last_updated TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            synced_at TEXT,
            record_count INTEGER,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()


def fetch_repos():
    """Call the external (GitHub) API and return parsed repo data."""
    # GitHub's API requires a User-Agent header on requests
    headers = {"User-Agent": "internal-sync-service"}
    response = requests.get(GITHUB_API_URL, headers=headers, timeout=10)
    response.raise_for_status()  # raises an exception for 4xx/5xx responses
    return response.json()


def upsert_repos(repos):
    """Insert or update repo records in the local SQLite store."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for repo in repos:
        cur.execute("""
            INSERT INTO repos (name, stars, language, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                stars=excluded.stars,
                language=excluded.language,
                last_updated=excluded.last_updated
        """, (
            repo.get("name"),
            repo.get("stargazers_count", 0),
            repo.get("language"),
            repo.get("updated_at"),
        ))
    conn.commit()
    conn.close()


def log_sync(record_count, status):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sync_log (synced_at, record_count, status) VALUES (?, ?, ?)",
        (datetime.datetime.utcnow().isoformat(), record_count, status),
    )
    conn.commit()
    conn.close()


@app.route("/sync", methods=["POST", "GET"])
def sync():
    """Trigger a sync from the external API into the local store."""
    try:
        repos = fetch_repos()
        upsert_repos(repos)
        log_sync(len(repos), "success")
        logger.info(f"Synced {len(repos)} records successfully.")
        return jsonify({
            "status": "success",
            "synced": len(repos),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }), 200

    except requests.exceptions.RequestException as e:
        # External API is down, rate-limited, or unreachable
        logger.error(f"Sync failed: {e}")
        log_sync(0, "failed")
        return jsonify({
            "status": "error",
            "message": "Failed to reach external API.",
            "detail": str(e),
        }), 502


@app.route("/status", methods=["GET"])
def status():
    """Return last sync time and current record count — basic health check."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM repos")
    record_count = cur.fetchone()[0]

    cur.execute("SELECT synced_at, status FROM sync_log ORDER BY id DESC LIMIT 1")
    last_sync = cur.fetchone()
    conn.close()

    return jsonify({
        "record_count": record_count,
        "last_sync_at": last_sync[0] if last_sync else None,
        "last_sync_status": last_sync[1] if last_sync else "never synced",
    }), 200


@app.route("/repos", methods=["GET"])
def list_repos():
    """List everything currently stored locally (the 'internal view' of the data)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, stars, language, last_updated FROM repos ORDER BY stars DESC")
    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {"name": r[0], "stars": r[1], "language": r[2], "last_updated": r[3]}
        for r in rows
    ]), 200


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "internal-sync-service",
        "endpoints": ["/sync", "/status", "/repos"],
    }), 200


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
