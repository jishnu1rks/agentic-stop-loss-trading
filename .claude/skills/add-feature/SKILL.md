---
name: add-feature
description: Add a new feature end-to-end (backend logic + API endpoint + frontend wiring) to the Agentic Stop-Loss Trading System - e.g. a new trade action, a new computed field, a new piece of trading logic. Use for anything bigger than a pure UI tweak (see the ui-update skill for that). Not for adding a new agent/strategy - see the new-agent skill for that specific case.
---

# Adding a feature - where logic goes and the full round-trip

This is a FastAPI + SQLAlchemy backend (`backend/app/`) and a React/Vite
frontend (`frontend/src/`), talking over a typed REST API. A typical
feature touches 4-6 files in a fixed order - follow it rather than
guessing file locations fresh each time.

## Backend layers (in the order you'll touch them)

1. **`models.py`** - SQLAlchemy `Trade`/`Agent`/`AgentLog` tables. Only
   add a column if the value needs to persist; a value computed fresh from
   existing data on every read (like unrealized P&L) doesn't need one -
   see `get_open_positions_pnl()` in `agent_runtime.py` for that pattern
   (compute-on-read, keyed by `trade_id`, merged onto rows client-side).
2. **`agent_runtime.py`** - this is where almost all trading logic lives:
   entry (`enter_position`), exit (`close_trade`, `force_close`), GTT
   bracket management (`modify_protection`), scan/monitor loops
   (`run_agent_scan`, `monitor_open_positions`), capital accounting
   (`get_capital_summary`). New trading behavior is a new function here,
   not inline in a router.
3. **`schemas.py`** - a Pydantic `*In` model for any new request body
   (validate shape/ranges here, e.g. `Field(gt=0)`), reuse `TradeOut` /
   `AgentOut` for responses where they already fit.
4. **`routers/{agents,trades,dashboard,cron}.py`** - thin: parse the
   request, call one `agent_runtime` function, translate exceptions to
   `HTTPException`. Business-rule validation (e.g. "stop-loss must be on
   the correct side of entry price") belongs in the router as a guard
   clause *before* calling into `agent_runtime`, so `agent_runtime`
   functions can assume valid input.
5. **`tests/test_*.py`** - `db_session` fixture (in-memory SQLite) +
   `FakeMarketDataAdapter` (see any existing test file for the pattern) -
   never hit real `yfinance` in a test. Test the `agent_runtime` function
   directly, not through HTTP.
6. Register new routers in `main.py` behind `Depends(require_auth)` like
   the existing ones, unless the endpoint must be publicly pollable
   (`/health`, and `/cron/tick` which is auth-gated but designed to be hit
   by an external pinger - see that file's docstring for why).

## Things that will bite you if skipped

- **GTT idempotency**: `BrokerAdapter.place_gtt()` is idempotent on
  `client_order_id` - calling it twice with the *same* id returns the
  *original* (possibly now-cancelled) GTT, not a new one. Any feature that
  re-arms a stop-loss/target (like `modify_protection`) must generate a
  **fresh** id each time (`f"{trade_id}:sl:{uuid4().hex[:8]}"`), and must
  explicitly `cancel_gtt()` the old one first - the simulator does not
  auto-cancel on overwrite.
- **Capital is a single shared pool**, not per-agent (Section 9-style hard
  constraint) - `get_capital_summary(db)["free_capital"]` is computed
  fresh from open positions + realized P&L, not a mutable balance column.
  Any new way to commit capital (a new trade action, etc.) should check
  free capital the same way `run_agent_scan`/`place_manual_trade` already
  do, not introduce a second accounting path.
- **Two schedulers exist and must both be considered**: the in-process
  APScheduler (`scheduler.py`, fires while the process happens to be
  awake) and `POST /cron/tick` (`routers/cron.py`, an external pinger
  directly triggers one scan+monitor cycle - the reliable path on
  sleep-prone free hosting). A feature that changes the scan/monitor logic
  in `agent_runtime.py` automatically affects both, since they call the
  same functions - don't add a third trigger path.
- **Direction matters everywhere**: buy vs. sell (short) flips which side
  of entry price is "stop-loss" vs. "target" (Section 4.1). Any new logic
  touching prices needs both branches - grep `trade.direction == "buy"` in
  `agent_runtime.py` for the existing pattern before writing a new
  comparison.
- **`is_manual` / `agent_id=None`** distinguishes manual trades from
  agent-placed ones (Section 7.7) - don't assume `agent_id` is always set.

## Frontend wiring (once the backend endpoint exists)

1. Add the type to `api/types.ts`, the method to the `api` object in
   `api/client.ts` (matches the endpoint's request/response shape exactly
   - copy an existing method like `editProtection` as a template).
2. Wire it into the component - see the `ui-update` skill for frontend
   conventions (Modal reuse, theming, column patterns).
3. Type-check (`cd frontend && npx tsc -b`) and run backend tests
   (`cd backend && source venv/bin/activate && pytest`) before calling it
   done.

## Restart

If uvicorn is running with `--reload` (the `run-dev` skill's documented
command), most backend edits pick up automatically. Still, after adding a
new router, a new DB column, or anything scheduler-related, kill and
restart it explicitly (`pkill -f "uvicorn app.main:app"`, then the
`run-dev` skill's start command) and confirm with `curl .../health` before
testing against the live local server - don't assume a save was enough.
