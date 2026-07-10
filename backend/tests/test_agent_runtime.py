from app.adapters.market_data.base import MarketDataAdapter, MarketDataSnapshot
from app.agent_runtime import (
    build_momentum_recommendations,
    build_watchlist_recommendations,
    close_trade_manually,
    enter_position,
    get_capital_summary,
    monitor_open_positions,
    run_agent_scan,
    stop_loss_price,
    target_price,
)
from app.models import Agent, AgentLog, Trade


class FakeMarketDataAdapter(MarketDataAdapter):
    def __init__(self, prices: dict, history: dict | None = None, volumes: dict | None = None):
        self.prices = prices
        self.history = history or {}
        self.volumes = volumes or {}

    def get_snapshot(self, symbols, lookback_days=20):
        return MarketDataSnapshot(
            prices={s: self.prices[s] for s in symbols if s in self.prices},
            history={s: self.history[s] for s in symbols if s in self.history},
            volumes={s: self.volumes[s] for s in symbols if s in self.volumes},
        )

    def is_market_open(self):
        return True


# ---- Section 4.1 stop-loss direction table ----

def test_buy_stop_loss_is_below_entry():
    assert stop_loss_price("buy", entry_price=100, stop_loss_pct=10) == 90.0


def test_sell_stop_loss_is_above_entry():
    assert stop_loss_price("sell", entry_price=100, stop_loss_pct=10) == 110.0


def test_buy_target_is_above_entry():
    assert target_price("buy", entry_price=100, target_pct=5) == 105.0


def test_sell_target_is_below_entry():
    assert target_price("sell", entry_price=100, target_pct=5) == 95.0


# ---- End-to-end entry -> GTT -> monitor -> exit ----

def test_long_position_exits_on_stop_loss_trigger(db_session, monkeypatch):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST",
        direction="buy",
        quantity=10,
        ref_price=100.0,
        buy_stop_loss_pct=10,
        sell_stop_loss_pct=10,
        target_pct=5,
        is_manual=True,
    )
    assert trade.status == "open"
    assert trade.stop_loss_price == 90.0
    assert trade.target_price == 105.0

    fake_adapter = FakeMarketDataAdapter({"TEST": 89.0})
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: fake_adapter)

    monitor_open_positions(db_session)

    db_session.refresh(trade)
    assert trade.status == "closed"
    assert trade.exit_reason == "stop_loss"
    assert trade.sell_price == 89.0
    assert trade.net_profit == trade.gross_profit - trade.charges - trade.tax


def test_long_position_exits_on_target_trigger(db_session, monkeypatch):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST2",
        direction="buy",
        quantity=10,
        ref_price=100.0,
        buy_stop_loss_pct=10,
        sell_stop_loss_pct=10,
        target_pct=5,
        is_manual=True,
    )

    fake_adapter = FakeMarketDataAdapter({"TEST2": 106.0})
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: fake_adapter)

    monitor_open_positions(db_session)

    db_session.refresh(trade)
    assert trade.status == "closed"
    assert trade.exit_reason == "target"


def test_manual_close_cancels_pending_gtts(db_session):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST3",
        direction="buy",
        quantity=10,
        ref_price=100.0,
        buy_stop_loss_pct=10,
        sell_stop_loss_pct=10,
        target_pct=5,
        is_manual=True,
    )

    close_trade_manually(db_session, trade, current_price=101.0)

    db_session.refresh(trade)
    assert trade.status == "closed"
    assert trade.exit_reason == "manual"
    assert trade.sell_price == 101.0


def test_short_position_profits_when_price_falls(db_session):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST4",
        direction="sell",
        quantity=10,
        ref_price=100.0,
        buy_stop_loss_pct=10,
        sell_stop_loss_pct=10,
        target_pct=5,
        is_manual=True,
    )
    assert trade.stop_loss_price == 110.0  # buy-back trigger above entry
    assert trade.target_price == 95.0

    close_trade_manually(db_session, trade, current_price=95.0)
    db_session.refresh(trade)
    assert trade.gross_profit == 50.0  # (100 - 95) * 10


# ---- Recommendations (live watchlist evaluation) ----

def _make_watchlist_agent(bands: dict) -> Agent:
    return Agent(
        agent_id="reco-agent",
        name="Reco Test Agent",
        strategy="watchlist_trigger",
        active=True,
        config={
            "universe": {"type": "watchlist", "value": list(bands)},
            "strategy_params": {"bands": bands},
            "risk": {
                "buy_stop_loss_pct": 2.0,
                "sell_stop_loss_pct": 2.0,
                "target_pct": 4.0,
                "position_size_type": "fixed_amount",
                "position_size_value": 10000,
                "max_concurrent_positions": 5,
                "max_daily_capital": 50000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": True},
        },
    )


def test_recommendation_for_symbol_in_band(db_session, monkeypatch):
    agent = _make_watchlist_agent({"FOO": {"direction": "buy", "low": 95, "high": 105}})
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 100.0}))

    recos = build_watchlist_recommendations(db_session, agent)

    assert len(recos) == 1
    reco = recos[0]
    assert reco["in_band"] is True
    assert reco["proximity_pct"] == 100.0
    assert reco["cmp"] == 100.0
    assert reco["target_price"] == 104.0
    assert reco["stop_loss_price"] == 98.0
    assert reco["already_open"] is False


def test_recommendation_for_symbol_outside_band_has_lower_proximity(db_session, monkeypatch):
    agent = _make_watchlist_agent({"FOO": {"direction": "buy", "low": 95, "high": 105}})
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 90.0}))

    recos = build_watchlist_recommendations(db_session, agent)

    assert recos[0]["in_band"] is False
    assert recos[0]["proximity_pct"] < 100.0


def test_recommendation_marks_already_open_positions(db_session, monkeypatch):
    agent = _make_watchlist_agent({"FOO": {"direction": "buy", "low": 95, "high": 105}})
    db_session.add(agent)
    db_session.commit()
    enter_position(
        db_session, agent_id="reco-agent", symbol="FOO", direction="buy", quantity=1,
        ref_price=100.0, buy_stop_loss_pct=2, sell_stop_loss_pct=2, target_pct=4,
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 100.0}))

    recos = build_watchlist_recommendations(db_session, agent)

    assert recos[0]["already_open"] is True


# ---- Momentum recommendations (universe-wide scan, no fixed watchlist) ----

def _make_momentum_agent(universe: list[str]) -> Agent:
    return Agent(
        agent_id="momentum-agent",
        name="Momentum Test Agent",
        strategy="momentum_breakout",
        active=True,
        config={
            "universe": {"type": "index", "value": universe},
            "strategy_params": {"lookback_days": 5, "breakout_threshold_pct": 2.0},
            "risk": {
                "buy_stop_loss_pct": 2.0,
                "sell_stop_loss_pct": 2.0,
                "target_pct": 4.0,
                "position_size_type": "fixed_amount",
                "position_size_value": 10000,
                "max_concurrent_positions": 10,
                "max_daily_capital": 100000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": True},
        },
    )


def test_momentum_recommendations_ranks_by_breakout_strength(db_session, monkeypatch):
    agent = _make_momentum_agent(["STRONG", "WEAK", "FLAT"])
    fake = FakeMarketDataAdapter(
        prices={"STRONG": 115.0, "WEAK": 102.0, "FLAT": 100.0},
        history={
            "STRONG": [100, 101, 100, 99, 100],  # prior high 101 -> +13.9%
            "WEAK": [100, 101, 100, 99, 100],  # prior high 101 -> +1.0% (below threshold)
            "FLAT": [100, 101, 100, 99, 100],  # prior high 101 -> -1.0%
        },
        volumes={
            "STRONG": [1000, 1000, 1000, 1000, 5000],
            "WEAK": [1000, 1000, 1000, 1000, 5000],
            "FLAT": [1000, 1000, 1000, 1000, 5000],
        },
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: fake)

    recos = build_momentum_recommendations(db_session, agent, top_n=10)

    assert [r["symbol"] for r in recos] == ["STRONG", "WEAK", "FLAT"]
    assert recos[0]["in_signal"] is True
    assert recos[1]["in_signal"] is False  # below breakout threshold
    assert recos[2]["in_signal"] is False  # not even above prior high


def test_momentum_recommendations_respects_top_n(db_session, monkeypatch):
    universe = [f"SYM{i}" for i in range(5)]
    prices = {s: 110.0 for s in universe}
    history = {s: [100, 101, 100, 99, 100] for s in universe}
    volumes = {s: [1000, 1000, 1000, 1000, 5000] for s in universe}
    fake = FakeMarketDataAdapter(prices=prices, history=history, volumes=volumes)
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: fake)

    agent = _make_momentum_agent(universe)
    recos = build_momentum_recommendations(db_session, agent, top_n=3)

    assert len(recos) == 3


# ---- Account-wide capital tracking ----

def test_capital_summary_with_no_trades_equals_starting_capital(db_session, monkeypatch):
    monkeypatch.setattr("app.agent_runtime.settings.account_starting_capital", 100_000.0)

    summary = get_capital_summary(db_session)

    assert summary["starting_capital"] == 100_000.0
    assert summary["capital_deployed"] == 0.0
    assert summary["realized_pnl"] == 0.0
    assert summary["free_capital"] == 100_000.0


def test_capital_summary_deducts_open_position_value(db_session, monkeypatch):
    monkeypatch.setattr("app.agent_runtime.settings.account_starting_capital", 100_000.0)
    enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=2, sell_stop_loss_pct=2, target_pct=4, is_manual=True,
    )

    summary = get_capital_summary(db_session)

    assert summary["capital_deployed"] == 1000.0
    assert summary["free_capital"] == 99_000.0


def test_capital_summary_adds_back_realized_profit(db_session, monkeypatch):
    monkeypatch.setattr("app.agent_runtime.settings.account_starting_capital", 100_000.0)
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=2, sell_stop_loss_pct=2, target_pct=4, is_manual=True,
    )
    close_trade_manually(db_session, trade, current_price=110.0)

    summary = get_capital_summary(db_session)

    assert summary["capital_deployed"] == 0.0
    assert summary["realized_pnl"] == trade.net_profit
    assert summary["free_capital"] == round(100_000.0 + trade.net_profit, 2)


def test_agent_scan_skips_entry_when_free_capital_insufficient(db_session, monkeypatch):
    monkeypatch.setattr("app.agent_runtime.settings.account_starting_capital", 500.0)
    monkeypatch.setattr(
        "app.agent_runtime.get_market_data_adapter",
        lambda: FakeMarketDataAdapter({"FOO": 100.0}),
    )

    agent = Agent(
        agent_id="capital-test-agent",
        name="Capital Test Agent",
        strategy="watchlist_trigger",
        active=True,
        config={
            "universe": {"type": "watchlist", "value": ["FOO"]},
            "strategy_params": {"bands": {"FOO": {"direction": "buy", "low": 95, "high": 105}}},
            "risk": {
                "buy_stop_loss_pct": 2.0,
                "sell_stop_loss_pct": 2.0,
                "target_pct": 4.0,
                "position_size_type": "fixed_amount",
                "position_size_value": 10000,  # would need 10x the account's free capital
                "max_concurrent_positions": 5,
                "max_daily_capital": 50000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": False},
        },
    )
    db_session.add(agent)
    db_session.commit()

    run_agent_scan(db_session, agent)

    assert db_session.query(Trade).count() == 0
    skipped_log = (
        db_session.query(AgentLog)
        .filter(AgentLog.decision == "skipped", AgentLog.reason == "insufficient free capital")
        .first()
    )
    assert skipped_log is not None


def test_agent_scan_commits_no_signal_logs_even_with_zero_signals(monkeypatch, tmp_path):
    """Regression test: a scan cycle that finds nothing to buy (the common
    case) must still persist its "no_signal" audit trail (Section 6.4).
    These were previously only db.add()'d, never committed, unless the scan
    also happened to enter at least one position - invisible to a same-
    session query (autoflush hides it), so this uses two separate
    connections against a real file-backed DB, the only way to actually
    prove a commit happened rather than just an in-memory flush."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base

    db_path = tmp_path / "regression.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr(
        "app.agent_runtime.get_market_data_adapter",
        lambda: FakeMarketDataAdapter({"FOO": 200.0}),  # price is nowhere near the band -> no signal
    )

    producer_session = Session()
    agent = Agent(
        agent_id="no-signal-agent",
        name="No Signal Agent",
        strategy="watchlist_trigger",
        active=True,
        config={
            "universe": {"type": "watchlist", "value": ["FOO"]},
            "strategy_params": {"bands": {"FOO": {"direction": "buy", "low": 95, "high": 105}}},
            "risk": {
                "buy_stop_loss_pct": 2.0,
                "sell_stop_loss_pct": 2.0,
                "target_pct": 4.0,
                "position_size_type": "fixed_amount",
                "position_size_value": 10000,
                "max_concurrent_positions": 5,
                "max_daily_capital": 50000,
            },
            "schedule": {"type": "interval", "interval_minutes": 5, "market_hours_only": False},
        },
    )
    producer_session.add(agent)
    producer_session.commit()

    run_agent_scan(producer_session, agent)
    producer_session.close()

    verifier_session = Session()
    try:
        no_signal_log = (
            verifier_session.query(AgentLog)
            .filter(AgentLog.agent_id == "no-signal-agent", AgentLog.decision == "no_signal")
            .first()
        )
        assert no_signal_log is not None
        assert no_signal_log.symbol == "FOO"
    finally:
        verifier_session.close()
