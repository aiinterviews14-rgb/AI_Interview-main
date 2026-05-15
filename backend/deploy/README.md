# Split backend deployment

The backend is organized into **two runnable parts** so you can package and scale them separately.

## Part 1 — Main API (`api.py`)

- **Module:** `api.py` exposes `app` (Flask).
- **Run locally:** `python api.py` (uses `start_flask_server`) or `gunicorn api:app`.
- **Responsibility:** Auth, payments, interviews, PDFs, admin, resume, DB — and **proctor routes** registered from `services/proctor_routes.py` on the same process (default).

Install:

```bash
pip install -r requirements.txt
# or
pip install -r requirements-core.txt
```

## Part 2 — Proctor worker (`run_proctor_server.py`)

- **Module:** `run_proctor_server.py` exposes `app` (Flask) with only proctoring endpoints + `GET /health`.
- **Run locally:** `set PROCTOR_PORT=5051` then `python run_proctor_server.py`.
- **Responsibility:** Same `/proctor/*` and `/api/start_monitoring` / `/api/stop_monitoring` handlers, isolated for a separate process or GPU host.

Install:

```bash
pip install -r requirements-proctor.txt
```

## Same machine vs two processes

| Mode | What to run |
|------|-------------|
| **Single process (simplest)** | Only `api.py`. Proctor blueprint is already included. |
| **Two processes (advanced)** | Main API **and** `run_proctor_server.py`. You must route browser/proxy traffic so **all** proctor calls hit **one** process that owns the active `InterviewManager` for that session. Two independent processes **do not** share in-memory `manager` / `proctor_service`; use one worker per interview or add a future HTTP session bridge. |

## Code layout

- `services/proctor_routes.py` — Flask **blueprint** with all proctor HTTP routes.
- `api.py` — Registers the blueprint after creating `manager` and `proctor_service`.

## Production note

If you run two backend processes in production, keep proctor traffic sticky to one process per active interview session. The interview manager is in-memory and not shared across independent workers.
