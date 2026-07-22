from app.adapters.market_data.base import MarketDataAdapter, MarketDataSnapshot
from app.models import Agent, AgentLog
from app.routers.cron import cron_tick


class FakeMarketDataAdapter(MarketDataAdapter):
    def __init__(self, prices: dict):
        self.prices = prices

    def get_snapshot(self, symbols, lookback_days=20):
        return MarketDataSnapshot(prices={s: self.prices[s] for s in symbols if s in self.prices}, history={})

    def is_market_open(self):
        return True

    def get_trending_symbols(self, sort_by="dayvolume", limit=15, min_market_cap=5_000_000_000):
        return list(self.prices.keys())[:limit]

    def get_fundamentals(self, symbol):
        return None


def _make_watchlist_agent(agent_id: str, active: bool) -> Agent:
    return Agent(
        agent_id=agent_id,
        name="Cron Test Agent",
        strategy="watchlist_trigger",
        active=active,
        config={
            "universe": {"type": "watchlist", "value": ["FOO"]},
            "strategy_params": {"bands": {"FOO": {"direction": "buy", "low": 95, "high": 105}}},
            "risk": {
                "buy_stop_loss_pct": 2.0,
                "sell_stop_loss_pct": 2.0,
                "target_pct": 4.0,
                "max_concurrent_positions": 5,
                "max_daily_capital": 50000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": False},
        },
    )


def test_cron_tick_scans_only_active_agents(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 100.0})
    )
    active_agent = _make_watchlist_agent("active-agent", active=True)
    inactive_agent = _make_watchlist_agent("inactive-agent", active=False)
    db_session.add_all([active_agent, inactive_agent])
    db_session.commit()

    result = cron_tick(db=db_session)

    assert result["agents_scanned"] == ["active-agent"]
    assert result["monitor_ran"] is True

    # The active agent's band matches the fake price -> it should have
    # actually entered a position, proving this is a real scan, not a no-op.
    logs = db_session.query(AgentLog).filter(AgentLog.agent_id == "active-agent").all()
    assert any(l.decision == "entered" for l in logs)
    # The inactive agent must not have been touched at all.
    assert db_session.query(AgentLog).filter(AgentLog.agent_id == "inactive-agent").count() == 0


def test_cron_tick_with_no_agents_still_runs_monitor(db_session):
    result = cron_tick(db=db_session)

    assert result["agents_scanned"] == []
    assert result["monitor_ran"] is True
