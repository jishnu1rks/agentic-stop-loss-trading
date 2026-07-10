---
name: new-agent
description: Scaffold a new trading agent for the Agentic Stop-Loss Trading System - either a new config using an existing strategy, or a brand-new pluggable strategy module. Use when the user asks to add/create a new agent, trading bot, or strategy for this project.
---

# Adding a new agent

Per the spec (Section 5.1-5.3): an agent = a config row (universe, risk
params, schedule) + a strategy module. Adding an agent using an *existing*
strategy needs no code changes at all - just a new config, created via the
API. Adding a genuinely new *strategy* (selection logic) needs a small new
Python module.

## Case A: new agent, existing strategy (e.g. another `watchlist_trigger` agent)

POST a config matching `app/schemas.py::AgentConfigIn` to `/agents`. Example:

```bash
curl -s -X POST http://127.0.0.1:8000/agents -H "Content-Type: application/json" -d '{
  "agent_id": "watchlist-trigger-02",
  "name": "My New Watchlist Agent",
  "active": true,
  "universe": {"type": "watchlist", "value": ["WIPRO", "SBIN"]},
  "strategy": "watchlist_trigger",
  "strategy_params": {
    "bands": {
      "WIPRO": {"direction": "buy", "low": 480, "high": 490},
      "SBIN": {"direction": "sell", "low": 800, "high": 815}
    }
  },
  "risk": {
    "buy_stop_loss_pct": 1.5,
    "sell_stop_loss_pct": 1.5,
    "target_pct": 3.0,
    "position_size_type": "fixed_amount",
    "position_size_value": 10000,
    "max_concurrent_positions": 5,
    "max_daily_capital": 50000
  },
  "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": true}
}'
```

Creating (or updating, via `PUT /agents/{agent_id}`) automatically
(re)schedules the APScheduler job for that agent - no restart needed.

Fill in real price bands (or ask the user for their entry criteria) rather
than guessing - illustrative bands won't trigger meaningful trades.

## Case B: a genuinely new strategy (new selection logic)

1. Create `backend/app/strategies/<name>.py` implementing the `Strategy`
   interface from `app/strategies/base.py`:

   ```python
   from app.adapters.market_data.base import MarketDataSnapshot
   from app.strategies.base import Signal, Strategy

   class MyNewStrategy(Strategy):
       def scan(self, universe: list[str], market_data: MarketDataSnapshot, params: dict) -> list[Signal]:
           signals = []
           for symbol in universe:
               price = market_data.prices.get(symbol)
               history = market_data.history.get(symbol, [])
               # ... your entry logic here ...
               if <entry condition met>:
                   signals.append(Signal(symbol=symbol, direction="buy", confidence=1.0, reason="..."))
           return signals
   ```

   Everything downstream (entry, GTT stop-loss/target placement, charges,
   tax, logging) is shared infrastructure (Section 4) - a strategy only
   returns signals, it never places orders itself.

2. Register it in `backend/app/strategies/__init__.py`:
   ```python
   from app.strategies.my_new_strategy import MyNewStrategy
   STRATEGY_REGISTRY["my_new_strategy"] = MyNewStrategy
   ```

3. Create an agent config as in Case A, with `"strategy": "my_new_strategy"`
   and whatever `strategy_params` your `scan()` expects.

4. Add a test in `backend/tests/test_strategies.py` mirroring
   `test_strategies.py::test_signal_fires_when_price_within_band` - build a
   `MarketDataSnapshot` by hand, assert on the returned `Signal` list. Don't
   hit real `yfinance` in strategy unit tests.

## Reference: two more strategy types the spec names but leaves unimplemented

Momentum Breakout (enter on N-day high break with volume confirmation) and
Mean-Reversion (enter on X% deviation below a moving average) are named in
Section 5.3 as the next agent types to build - `market_data.history` (a
list of recent daily closes, oldest first) is already available on the
snapshot for exactly this kind of lookback logic.
