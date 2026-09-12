# Internal Data Sync Service

A lightweight internal-style service (Python + Flask) that pulls data from an
external API (GitHub's public repo API) and keeps a local SQLite store in
sync — with health/status monitoring and graceful error handling for when
the external API is unavailable or rate-limited.

This mirrors a common **Application Engineering** pattern: integrating a
third-party/vendor system with an internal data store and exposing that
integration as a simple internal service that other tools or teams can rely on.

## Endpoints

| Method | Route      | Description                                              |
|--------|------------|-----------------------------------------------------------|
| GET    | `/`        | Lists available endpoints                                  |
| GET/POST | `/sync`  | Triggers a sync from the external API into the local store |
| GET    | `/status` | Returns last sync time, status, and current record count   |
| GET    | `/repos`  | Lists all locally stored records (the "internal view")     |

## Design notes

- **Upsert logic**: records are inserted or updated based on a unique key
  (repo name), so repeated syncs don't create duplicates.
- **Sync logging**: every sync attempt (success or failure) is logged to a
  `sync_log` table with a timestamp, so `/status` can report real history.
- **Error handling**: if the external API is down, rate-limited, or
  unreachable, the service catches the failure, logs it, and returns a clean
  `502` JSON error instead of crashing — verified against a real rate-limited
  response from GitHub's API during testing.

## Running it

```bash
pip install flask requests
python app.py
```

Then visit:
- `http://127.0.0.1:5000/sync` to trigger a sync
- `http://127.0.0.1:5000/status` to check sync health
- `http://127.0.0.1:5000/repos` to see the synced data

## Possible extensions

- Swap the GitHub API for an internal or vendor API (e.g. Salesforce) to
  more directly mirror integrating vendor-sourced enterprise software.
- Add a scheduled sync (cron job or `APScheduler`) instead of manual triggers.
- Add a minimal front-end to visualize `/repos` and `/status`.
