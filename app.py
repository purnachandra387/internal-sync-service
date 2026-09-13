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

from flask import Flask, jsonify, request
import requests
import sqlite3
import datetime
import logging

import salesforce_client

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
            status TEXT,
            source TEXT DEFAULT 'github'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS salesforce_contacts (
            sf_id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            title TEXT,
            last_modified TEXT
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


def log_sync(record_count, status, source="github"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sync_log (synced_at, record_count, status, source) VALUES (?, ?, ?, ?)",
        (datetime.datetime.utcnow().isoformat(), record_count, status, source),
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
    repo_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM salesforce_contacts")
    contact_count = cur.fetchone()[0]

    cur.execute("SELECT synced_at, status, source FROM sync_log WHERE source='github' ORDER BY id DESC LIMIT 1")
    last_github_sync = cur.fetchone()

    cur.execute("SELECT synced_at, status, source FROM sync_log WHERE source='salesforce' ORDER BY id DESC LIMIT 1")
    last_sf_sync = cur.fetchone()

    conn.close()

    return jsonify({
        "github": {
            "record_count": repo_count,
            "last_sync_at": last_github_sync[0] if last_github_sync else None,
            "last_sync_status": last_github_sync[1] if last_github_sync else "never synced",
        },
        "salesforce": {
            "record_count": contact_count,
            "last_sync_at": last_sf_sync[0] if last_sf_sync else None,
            "last_sync_status": last_sf_sync[1] if last_sf_sync else "never synced",
        },
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


def upsert_salesforce_contacts(contacts):
    """Insert or update Salesforce Contact records in the local SQLite store."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for c in contacts:
        cur.execute("""
            INSERT INTO salesforce_contacts (sf_id, name, email, phone, title, last_modified)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sf_id) DO UPDATE SET
                name=excluded.name,
                email=excluded.email,
                phone=excluded.phone,
                title=excluded.title,
                last_modified=excluded.last_modified
        """, (
            c.get("Id"),
            c.get("Name"),
            c.get("Email"),
            c.get("Phone"),
            c.get("Title"),
            c.get("LastModifiedDate"),
        ))
    conn.commit()
    conn.close()


@app.route("/salesforce/sync", methods=["POST", "GET"])
def salesforce_sync():
    """Pull Contact records from Salesforce (vendor system) into the local store."""
    try:
        contacts = salesforce_client.fetch_contacts(limit=25)
        upsert_salesforce_contacts(contacts)
        log_sync(len(contacts), "success", source="salesforce")
        logger.info(f"Synced {len(contacts)} Salesforce contacts.")
        return jsonify({
            "status": "success",
            "synced": len(contacts),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }), 200

    except salesforce_client.SalesforceAuthError as e:
        logger.error(f"Salesforce auth failed: {e}")
        log_sync(0, "auth_failed", source="salesforce")
        return jsonify({"status": "error", "message": "Salesforce authentication failed.", "detail": str(e)}), 401

    except salesforce_client.SalesforceAPIError as e:
        logger.error(f"Salesforce API call failed: {e}")
        log_sync(0, "failed", source="salesforce")
        return jsonify({"status": "error", "message": "Salesforce API call failed.", "detail": str(e)}), 502

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error reaching Salesforce: {e}")
        log_sync(0, "failed", source="salesforce")
        return jsonify({"status": "error", "message": "Could not reach Salesforce.", "detail": str(e)}), 502


@app.route("/salesforce/contacts", methods=["GET"])
def salesforce_contacts():
    """List locally stored Salesforce contacts (the internal view of vendor data)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sf_id, name, email, phone, title, last_modified FROM salesforce_contacts ORDER BY name")
    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {"id": r[0], "name": r[1], "email": r[2], "phone": r[3], "title": r[4], "last_modified": r[5]}
        for r in rows
    ]), 200


@app.route("/salesforce/contacts", methods=["POST"])
def salesforce_create_contact():
    """
    Create a Contact in Salesforce from a JSON body:
    {"first_name": "...", "last_name": "...", "email": "..."}
    Demonstrates writing to the vendor system, not just reading from it.
    """
    data = request.get_json(force=True, silent=True) or {}
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    email = data.get("email")

    if not last_name:
        return jsonify({"status": "error", "message": "last_name is required."}), 400

    try:
        result = salesforce_client.create_contact(first_name, last_name, email)
        return jsonify({"status": "success", "salesforce_id": result.get("id")}), 201

    except salesforce_client.SalesforceAuthError as e:
        return jsonify({"status": "error", "message": "Salesforce authentication failed.", "detail": str(e)}), 401

    except salesforce_client.SalesforceAPIError as e:
        return jsonify({"status": "error", "message": "Salesforce API call failed.", "detail": str(e)}), 502


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "internal-sync-service",
        "endpoints": [
            "/sync", "/status", "/repos",
            "/salesforce/sync", "/salesforce/contacts",
        ],
    }), 200


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)