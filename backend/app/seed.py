"""
Seed one example Watchlist-Trigger agent (Section 5.2/5.3) so there's
something to scan immediately after setup. Entry bands are centered on each
symbol's current live price (+/- 0.5%) purely so a demo scan actually fires
a signal - replace with real bands before relying on this agent.

If the live feed is unreachable (yfinance can rate-limit/block bursts on
some networks - see the `run-dev` skill's known-limitations note), this
falls back to static illustrative bands so setup still completes.

Run with: python -m app.seed
"""
from app.adapters.market_data.yfinance_adapter import (
    MarketDataUnavailableError,
    YFinanceMarketDataAdapter,
)
from app.db import SessionLocal, init_db
from app.models import Agent

WATCHLIST = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

# Fallback if the live feed is unreachable at seed-time.
FALLBACK_BANDS = {
    "RELIANCE": ("buy", 2900.0, 2950.0),
    "TCS": ("sell", 3800.0, 3850.0),
    "INFY": ("buy", 1800.0, 1830.0),
    "HDFCBANK": ("sell", 1650.0, 1680.0),
    "ICICIBANK": ("buy", 1200.0, 1220.0),
}


def build_bands() -> dict:
    try:
        adapter = YFinanceMarketDataAdapter()
        snapshot = adapter.get_snapshot(WATCHLIST, lookback_days=5)
        bands = {}
        for i, symbol in enumerate(WATCHLIST):
            price = snapshot.prices[symbol]
            direction = "buy" if i % 2 == 0 else "sell"
            bands[symbol] = {
                "direction": direction,
                "low": round(price * 0.995, 2),
                "high": round(price * 1.005, 2),
            }
        return bands
    except MarketDataUnavailableError as exc:
        print(f"Live feed unavailable ({exc}), falling back to illustrative bands.")
        return {
            symbol: {"direction": direction, "low": low, "high": high}
            for symbol, (direction, low, high) in FALLBACK_BANDS.items()
        }


def seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Agent).filter(Agent.agent_id == "watchlist-trigger-01").first():
            print("Agent 'watchlist-trigger-01' already exists, skipping seed.")
            return

        bands = build_bands()
        config = {
            "agent_id": "watchlist-trigger-01",
            "name": "NSE Blue-Chip Watchlist Trigger",
            "active": True,
            "universe": {"type": "watchlist", "value": WATCHLIST},
            "strategy": "watchlist_trigger",
            "strategy_params": {"bands": bands},
            "risk": {
                "buy_stop_loss_pct": 1.5,
                "sell_stop_loss_pct": 1.5,
                "target_pct": 3.0,
                "max_concurrent_positions": 5,
                "max_daily_capital": 50000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": True},
        }
        agent = Agent(
            agent_id=config["agent_id"],
            name=config["name"],
            strategy=config["strategy"],
            config=config,
            active=True,
        )
        db.add(agent)
        db.commit()
        print(f"Seeded agent '{agent.agent_id}' with bands: {bands}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
