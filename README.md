# Agentic Stop-Loss Trading System (Phase 1: Simulation)

Implements the spec in `agentic_stop_loss_trading_spec.docx`: autonomous
trading agents that scan a stock universe, enter positions, immediately
protect them with a GTT-style stop-loss (and optional target), and log the
full trade lifecycle including a cost breakdown (charges vs. tax, kept
separate per Section 6.3).

This build covers **Phase 1 (local simulation)** only, per the spec's own
phased rollout (Section 3.2): agents trade against real/delayed NSE data
via `yfinance`, but no real broker orders are ever placed. The Broker
Adapter and Market Data Adapter are written as interchangeable interfaces
(Section 3.1) so Phase 2 (Zerodha Kite Connect) and Phase 3 (Claude MCP as
a reasoning backend) can be added later without touching agent logic.

## What's implemented

- **Data model** (Section 6): `trades`, `agents`, `agent_logs` tables via
  SQLAlchemy, SQLite by default (`DATABASE_URL` swaps to Postgres with no
  code change).
- **Broker Adapter** (Section 3.1/9): `SimulatorBrokerAdapter` — in-memory
  paper broker, idempotent on `client_order_id` (no duplicate GTTs on
  retries), GTT stop-loss/target orders that trigger against live prices.
- **Market Data Adapter**: `YFinanceMarketDataAdapter` — NSE quotes/history
  via `yfinance`; raises `MarketDataUnavailableError` on failure so agents
  **pause rather than trade on stale data** (Section 9 fail-safe).
- **Strategy framework** (Section 5.3): pluggable `Strategy.scan()`
  interface; `WatchlistTriggerStrategy` implemented (the "simplest agent"
  the spec calls out). Momentum Breakout / Mean-Reversion are stubbed out
  as an open item (see `new-agent` skill) — `MarketDataSnapshot.history`
  is already there for whoever builds them.
- **Core trading flow** (Section 4): Scan → Signal → Entry → Protect →
  Monitor → Exit → Log, with the stop-loss direction table from Section
  4.1 implemented directly (`app/agent_runtime.py`). A time-based exit
  (`risk.max_hold_hours`, optional per agent) is also wired up.
- **Charges vs. tax** (Section 6.3): kept as separate fields everywhere;
  charges use a Zerodha-like NSE equity charge structure (brokerage, STT,
  exchange, SEBI, stamp duty, GST); tax is a flat STCG estimate — both are
  dashboard estimates, not filing-ready figures.
- **Scheduler** (Section 8/9): APScheduler — each active agent gets its own
  interval job; a single shared job polls all open positions for GTT
  triggers every minute; a bounded thread pool caps concurrent scans.
- **Dashboard** (Section 7): KPI cards, profit/capital/frequency/win-rate
  charts, duration histogram, per-agent breakdown table, sortable/
  filterable trade log, and a manual Buy/Sell form (Section 7.7) that goes
  through the same Broker Adapter as agents and is tagged `is_manual`
  rather than attributed to an agent.

## Assumptions made where the spec left things open (Section 10)

- **Short-selling / delivery vs. intraday** (charges depend on this): a
  `buy`-direction trade is treated as delivery (can be held multi-day); a
  `sell` (short) trade is treated as intraday/MIS, since naked short
  selling in cash equities must be squared off same-day on NSE. This
  changes which charge lines apply — see `app/charges.py`.
- **Position sizing**: `fixed_amount` (spec's example) and `pct_capital`
  (simple fraction of `max_daily_capital`) are implemented;
  volatility-based sizing is not.
- **Tax computation**: flat 20% STCG-style rate on positive net gains,
  configurable via `STCG_TAX_PCT`. Confirm actual treatment with a tax
  professional — this is explicitly a dashboard estimate (Section 6.3).
- **First strategy built**: Watchlist-Trigger only, per your earlier
  choice — see the `new-agent` skill for adding Momentum Breakout,
  Mean-Reversion, or an entirely new strategy.

## Project layout

```
backend/
  app/
    config.py             # env-driven settings incl. charge/tax rates
    models.py             # SQLAlchemy: Agent, Trade, AgentLog
    schemas.py             # Pydantic request/response schemas
    charges.py / tax.py     # Section 6.3 cost model
    agent_runtime.py         # Section 4 core flow + Section 4.1 direction logic
    scheduler.py              # APScheduler wiring
    seed.py                    # seeds one example watchlist_trigger agent
    adapters/
      broker/                    # BrokerAdapter interface + simulator
      market_data/                # MarketDataAdapter interface + yfinance
    strategies/                    # Strategy interface + watchlist_trigger
    routers/                        # agents / trades / dashboard endpoints
  tests/                             # pytest - charges, tax, strategy, full trade flow
frontend/
  src/
    api/                               # typed API client
    components/                         # KPI cards, charts, tables, manual trade form
    App.tsx
.claude/skills/                          # run-dev, new-agent, trade-stats
```

## Running it

See the `run-dev` Claude Code skill for the full step-by-step, or:

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Dashboard: http://127.0.0.1:5173 · API: http://127.0.0.1:8000 (docs at `/docs`)

Run tests: `cd backend && source venv/bin/activate && pytest`

## Deploying to production

This deploys the Phase 1 **simulator** (paper trading) to run 24/7 on a
real server, gated behind a single shared login. It does not enable live
trading — that still requires building the Kite Connect adapter (Phase 2).

**Why not just leave it running on a laptop:** the scheduler
(`app/scheduler.py`) only runs while the backend process is alive. A
deployed, always-on server is what makes "autonomous" actually mean
"runs without you."

### Stack

- **Backend**: Docker container (`backend/Dockerfile`) on an **always-on**
  paid tier — not a free/sleep-on-idle tier. If the process sleeps, the
  scheduler stops firing and agents stop scanning, silently.
- **Database**: Postgres, not SQLite — most PaaS filesystems are ephemeral
  and would lose `trading.db` on every redeploy/restart. `DATABASE_URL`
  is already portable (Section 6); `postgres://` URLs are auto-normalized
  to `postgresql://` in `app/db.py`.
- **Frontend**: static build (`npm run build` → `frontend/dist`), served
  by any static host.
- **Auth**: single shared login (HTTP Basic Auth via `BASIC_AUTH_USERNAME`
  / `BASIC_AUTH_PASSWORD`) gates every route except `/health`. Unset in
  local dev = no login screen at all - it only activates once configured.

### Critical constraint: one process, one worker

APScheduler runs in-process (Section 8). A second worker or a second
running instance would each run their own copy of the scheduler, and
every agent would double-scan and could double-enter trades. The
Dockerfile hardcodes `--workers 1` - do not change this or run more than
one instance of the backend against the same database.

### Deploying on Render (recommended - `render.yaml` blueprint included)

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, point it at the repo. It reads
   `render.yaml` and creates the backend web service, a Postgres
   database, and the frontend static site together (currently configured
   on Render's **free** tier - see the caveats below and upgrade to a
   paid always-on plan for real production use, not just a client demo).
3. On the backend service, set `BASIC_AUTH_USERNAME` and
   `BASIC_AUTH_PASSWORD` in the Render dashboard (deliberately not in
   `render.yaml`/git - see `sync: false`).
4. Once both services are live, update `CORS_ORIGINS` on the backend and
   `VITE_API_BASE_URL` on the frontend to each other's actual Render
   URLs if they differ from the `render.yaml` defaults, and redeploy.
5. Visit the frontend URL, log in with the credentials from step 3, and
   `python -m app.seed` (via Render's shell) or the Agent Settings page
   to configure agents - a fresh Postgres database starts with none.

### Free hosting for a demo

`render.yaml` defaults to Render's **free** tier for the backend, which
is a real product tradeoff, not just "the same thing but slower":

- **The instance sleeps after 15 minutes with no HTTP traffic**, and
  since APScheduler runs in-process, **the scheduler stops firing while
  asleep** - agents don't scan autonomously unless something is actively
  hitting the site. The next visit wakes it with a ~30-50s cold start.
- **Fix, still free**: point an external uptime pinger (e.g.
  [UptimeRobot](https://uptimerobot.com) or
  [cron-job.org](https://cron-job.org), both free) at
  `https://<your-backend>.onrender.com/health` every 5-10 minutes. This
  keeps the instance continuously awake, so the scheduler actually runs
  autonomously - and a single service pinged this way stays within
  Render's free 750 instance-hours/month (≈ one service running 24/7 for
  a 30-day month), so this costs nothing extra.
- **Render's free Postgres has historically had a retention/expiration
  window** (check Render's current terms) - fine for a short client demo,
  risky if it needs to run for weeks. If that matters, swap in
  [Neon](https://neon.tech) (generous free tier, no forced deletion,
  auto-suspends but keeps data) instead of the Render-managed database:
  create a Neon project, copy its connection string, and set it as
  `DATABASE_URL` directly on the Render backend service instead of using
  `fromDatabase` in `render.yaml`.
- The single-worker constraint above still applies on free tier too -
  Render's free plan is one instance anyway, so this isn't an extra risk.

### Deploying elsewhere (Railway, Fly.io, your own VM)

The same three pieces apply regardless of platform: build
`backend/Dockerfile` as a single-instance service, provision Postgres and
set `DATABASE_URL`, and serve `frontend/dist` as a static site with
`VITE_API_BASE_URL` pointed at the backend. Set
`BASIC_AUTH_USERNAME`/`BASIC_AUTH_PASSWORD`/`CORS_ORIGINS` the same way.
Railway and Fly.io both have free/hobby tiers with similar sleep-on-idle
tradeoffs to Render's - the keep-alive-ping trick above applies there too.

## Known limitation

`yfinance` is unofficial and gets rate-limited (HTTP 429) or blocked
without notice on some networks — when that happens, agents log a
`paused` decision and manual trades return a 503 rather than trading on
missing data. That's the Section 9 fail-safe behaving correctly, not a
bug in this app.

## Disclaimer

This is Phase 1 **simulation only** — no real orders are ever placed. Per
Section 9: once Phase 2 (live Kite Connect) is wired up, this system
executes real trades with real capital. It is not financial advice, and
stop-loss orders do not guarantee execution at the exact trigger price
(slippage risk, especially in volatile/illiquid stocks).
# agentic-stop-loss-trading
