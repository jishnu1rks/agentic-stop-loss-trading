---
name: run-dev
description: Start or restart the Agentic Stop-Loss Trading System's backend (FastAPI) and frontend (React dashboard) for local Phase-1 simulation development. Use when the user asks to run, start, restart, or check on this app/dashboard/backend/frontend.
---

# Running the Agentic Stop-Loss Trading System

This project has two halves that both need to be running:

- **Backend**: `backend/` — FastAPI + SQLite (Phase 1 simulation), APScheduler
  runs each active agent's scan on its own interval plus a shared 1-minute
  GTT-monitor job. Serves the API on port 8000.
- **Frontend**: `frontend/` — Vite + React dashboard on port 5173, talks to
  the backend via `VITE_API_BASE_URL` (defaults to `http://127.0.0.1:8000`).

## Steps

1. **Check the backend venv exists**; create it if not:
   ```bash
   cd backend
   [ -d venv ] || python3 -m venv venv
   source venv/bin/activate
   pip install -q -r requirements.txt
   ```

2. **Check `.env` exists**; if not, copy the example (defaults are fine for
   local simulation — no real credentials needed in Phase 1):
   ```bash
   [ -f .env ] || cp .env.example .env
   ```

3. **Seed the DB if empty** (first run only — `trading.db` won't exist yet):
   ```bash
   [ -f trading.db ] || python -m app.seed
   ```
   This creates one example `watchlist_trigger` agent
   (`watchlist-trigger-01`). Its price bands are static/illustrative
   (see `app/seed.py`) — edit them or create a new agent via the API
   (see the `new-agent` skill) before expecting it to actually trade.

4. **Start the backend** (background it — this is a long-running dev
   server, not a one-shot command):
   ```bash
   nohup uvicorn app.main:app --reload --port 8000 > /tmp/stop-loss-backend.log 2>&1 &
   ```
   Verify with `curl -s http://127.0.0.1:8000/health` — should return
   `{"status":"ok"}`.

5. **Start the frontend**, from the `frontend/` directory:
   ```bash
   cd ../frontend
   npm install   # first run only
   npm run dev -- --port 5173 &
   ```
   Or use the `preview_start`/`preview_*` tools if available for browser
   verification — note that this repo's Python venv has been observed to
   trip some sandboxed preview environments' `getcwd`/symlink restrictions
   on `venv/bin/*`; if `preview_start` fails on the backend for that reason,
   just run the backend via a plain background shell command instead (the
   frontend can still reach it over HTTP either way).

6. Open `http://127.0.0.1:5173`. If the dashboard shows "Could not reach
   the backend API," the backend isn't up yet or is on the wrong port.

## Known limitation

`yfinance` (the Phase-1 market data adapter) can be rate-limited or
unreachable in restricted network environments — the app is designed to
**pause rather than trade on missing data** (Section 9 fail-safe), so a
"Market data unavailable" error on a manual trade or a `paused` row in
`agent_logs` means the feed is the problem, not the app.
