---
name: trade-stats
description: Query the running Agentic Stop-Loss Trading System backend for a summary of trades, KPIs, and per-agent performance. Use when the user asks how their agents/trades are doing, wants a P&L summary, or asks about open positions - without opening the dashboard themselves.
---

# Trade / dashboard stats

The backend must already be running (see the `run-dev` skill) at
`http://127.0.0.1:8000`. Pull the same data the dashboard shows, then
summarize it in prose rather than dumping raw JSON.

## Useful endpoints

```bash
# Headline KPIs (Section 7.2): trade counts, net profit, capital, open positions, charges/tax
curl -s http://127.0.0.1:8000/dashboard/kpis | python3 -m json.tool

# Per-agent breakdown (Section 7.5): trades, win rate, net profit, avg duration, active/inactive
curl -s http://127.0.0.1:8000/dashboard/agents-breakdown | python3 -m json.tool

# Win rate mix - target vs. stop-loss vs. manual vs. timeout exits (Section 7.3)
curl -s http://127.0.0.1:8000/dashboard/win-rate | python3 -m json.tool

# Duration metrics - avg hold time by exit reason + histogram buckets (Section 7.4)
curl -s http://127.0.0.1:8000/dashboard/duration-metrics | python3 -m json.tool

# Raw trade log, filterable (Section 7.6) - e.g. only this agent's open trades
curl -s "http://127.0.0.1:8000/trades?agent_id=watchlist-trigger-01&status=open" | python3 -m json.tool

# Only manual trades (Section 7.7), or only agent trades:
curl -s "http://127.0.0.1:8000/trades?is_manual=true" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/trades?is_manual=false" | python3 -m json.tool

# Scan/decision audit trail (Section 6.4) - why an agent did or didn't trade,
# straight from the DB (no HTTP endpoint exposes this yet):
cd backend && source venv/bin/activate && python3 -c "
from app.db import SessionLocal
from app.models import AgentLog
db = SessionLocal()
for row in db.query(AgentLog).order_by(AgentLog.timestamp.desc()).limit(20):
    print(row.timestamp, row.agent_id, row.symbol, row.decision, row.reason)
"
```

## What to report

- Lead with net profit (all-time and this month) and open position count -
  that's what the user almost always actually wants to know first.
- Call out charges and tax separately (Section 6.3 keeps them distinct on
  purpose) - don't collapse them into one "costs" number.
- If a per-agent breakdown is requested, rank by net profit and flag any
  agent with 0 trades (likely means its entry criteria/bands never matched
  - check `agent_logs` for `no_signal`/`paused` rows before assuming it's
  broken).
- If `agent_logs` shows repeated `paused` rows with "market data
  unavailable," say so plainly - that's the Section 9 fail-safe working as
  intended (the feed is down/rate-limited), not an app bug.
