from app.adapters.market_data.base import MarketDataAdapter, MarketDataSnapshot
from app.agent_runtime import (
    build_momentum_recommendations,
    build_watchlist_recommendations,
    close_trade_manually,
    enter_position,
    estimate_trade_charges,
    get_capital_summary,
    get_open_positions_pnl,
    modify_protection,
    monitor_open_positions,
    resolve_universe,
    run_agent_scan,
    stop_loss_price,
    target_price,
    trade_budget,
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

    def get_trending_symbols(self, sort_by="dayvolume", limit=15, min_market_cap=5_000_000_000):
        return list(self.prices.keys())[:limit]

    def get_fundamentals(self, symbol):
        return None


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


# ---- Net P&L breakup popup ----

def test_estimate_trade_charges_matches_stored_totals_for_closed_trade(db_session):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST5",
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

    breakdown = estimate_trade_charges(trade, trade.sell_price)

    assert breakdown["is_estimate"] is False
    assert breakdown["total_charges"] == trade.charges
    assert breakdown["tax"] == trade.tax
    assert breakdown["net_profit"] == trade.net_profit
    # line items should sum to the stored total
    line_items = (
        breakdown["brokerage"]
        + breakdown["stt"]
        + breakdown["exchange_txn"]
        + breakdown["sebi_charges"]
        + breakdown["stamp_duty"]
        + breakdown["gst"]
    )
    assert round(line_items, 2) == breakdown["total_charges"]


def test_estimate_trade_charges_is_marked_estimate_for_open_trade(db_session):
    trade = enter_position(
        db_session,
        agent_id=None,
        symbol="TEST6",
        direction="buy",
        quantity=10,
        ref_price=100.0,
        buy_stop_loss_pct=10,
        sell_stop_loss_pct=10,
        target_pct=5,
        is_manual=True,
    )

    breakdown = estimate_trade_charges(trade, 103.0)

    assert breakdown["is_estimate"] is True
    assert breakdown["reference_price"] == 103.0
    assert breakdown["gross_profit"] == 30.0  # (103 - 100) * 10


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
    # Less than the price of a single share (100.0) - there's no fixed
    # per-trade amount any more, a signal just spends whatever's free, so
    # this is the only way "not enough capital" can still happen.
    monkeypatch.setattr("app.agent_runtime.settings.account_starting_capital", 50.0)
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
        .filter(AgentLog.decision == "skipped", AgentLog.reason == "insufficient capital for even 1 share")
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


# ---- Unrealized P&L for open positions ----

def test_unrealized_pnl_positive_for_buy_when_price_rises(db_session, monkeypatch):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 105.0}))

    pnl = get_open_positions_pnl(db_session)

    assert pnl[trade.trade_id]["current_price"] == 105.0
    assert pnl[trade.trade_id]["unrealized_pnl"] == 50.0  # (105-100)*10
    assert pnl[trade.trade_id]["unrealized_pnl_pct"] == 5.0


def test_unrealized_pnl_positive_for_short_when_price_falls(db_session, monkeypatch):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="sell", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 95.0}))

    pnl = get_open_positions_pnl(db_session)

    assert pnl[trade.trade_id]["unrealized_pnl"] == 50.0  # (100-95)*10


def test_heading_pct_midpoint_between_stop_loss_and_target(db_session, monkeypatch):
    # buy at 100, stop-loss 10% -> 90, target 10% -> 110
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )

    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 100.0}))
    assert get_open_positions_pnl(db_session)[trade.trade_id]["heading_pct"] == 50.0

    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 90.0}))
    assert get_open_positions_pnl(db_session)[trade.trade_id]["heading_pct"] == 0.0

    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 110.0}))
    assert get_open_positions_pnl(db_session)[trade.trade_id]["heading_pct"] == 100.0


def test_heading_pct_none_when_no_target_configured(db_session, monkeypatch):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=None, is_manual=True,
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 100.0}))

    assert get_open_positions_pnl(db_session)[trade.trade_id]["heading_pct"] is None


def test_open_positions_pnl_empty_when_no_open_trades(db_session):
    assert get_open_positions_pnl(db_session) == {}


def test_open_positions_pnl_omits_trade_with_unavailable_price(db_session, monkeypatch):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({}))

    assert trade.trade_id not in get_open_positions_pnl(db_session)


# ---- Editing stop-loss / target on an open position ----

def test_modify_protection_updates_trade_levels(db_session):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    assert trade.stop_loss_price == 90.0
    assert trade.target_price == 110.0

    modify_protection(db_session, trade, new_stop_loss_price=95.0, new_target_price=120.0)

    db_session.refresh(trade)
    assert trade.stop_loss_price == 95.0
    assert trade.target_price == 120.0
    # pct is recomputed off the entry price so downstream displays stay right
    assert trade.stop_loss_pct == 5.0
    assert trade.target_pct == 20.0


def test_modify_protection_rearms_gtt_at_new_level(db_session, monkeypatch):
    # Original SL is 90; move it up to 96. A price of 95 should now trigger
    # the new stop-loss even though it wouldn't have touched the old one.
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    modify_protection(db_session, trade, new_stop_loss_price=96.0, new_target_price=110.0)

    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 95.0}))
    monitor_open_positions(db_session)

    db_session.refresh(trade)
    assert trade.status == "closed"
    assert trade.exit_reason == "stop_loss"


def test_modify_protection_can_remove_target(db_session, monkeypatch):
    trade = enter_position(
        db_session, agent_id=None, symbol="FOO", direction="buy", quantity=10,
        ref_price=100.0, buy_stop_loss_pct=10, sell_stop_loss_pct=10, target_pct=10, is_manual=True,
    )
    modify_protection(db_session, trade, new_stop_loss_price=90.0, new_target_price=None)

    db_session.refresh(trade)
    assert trade.target_price is None
    assert trade.target_gtt_id is None

    # Price rising to the old target (110) must NOT close it any more.
    monkeypatch.setattr("app.agent_runtime.get_market_data_adapter", lambda: FakeMarketDataAdapter({"FOO": 111.0}))
    monitor_open_positions(db_session)
    db_session.refresh(trade)
    assert trade.status == "open"


# ---- Section 5.1 screener universe - standard fundamentals bar ----

class FakeScreenerAdapter(FakeMarketDataAdapter):
    def __init__(self, trending: list[str], fundamentals_by_symbol: dict):
        super().__init__({s: 100.0 for s in trending})
        self.trending = trending
        self.fundamentals_by_symbol = fundamentals_by_symbol

    def get_trending_symbols(self, sort_by="dayvolume", limit=15, min_market_cap=5_000_000_000):
        return self.trending

    def get_fundamentals(self, symbol):
        return self.fundamentals_by_symbol.get(symbol)


def test_resolve_universe_screener_drops_unrecommendable_symbols():
    adapter = FakeScreenerAdapter(
        trending=["GOOD", "BAD", "UNKNOWN"],
        fundamentals_by_symbol={
            "GOOD": {"debt_to_equity": 40.0, "peg": 0.8, "insider_holding_pct": 0.5},
            "BAD": {"debt_to_equity": 350.0},  # hard red flag
        },
    )
    config = {"universe": {"type": "screener", "screener": {}}}

    universe = resolve_universe(config, adapter)

    assert "GOOD" in universe
    assert "BAD" not in universe
    # A symbol with no fetchable fundamentals is kept, not dropped.
    assert "UNKNOWN" in universe


# ---- Per-trade budget cap (25% of max_daily_capital) ----

def test_trade_budget_caps_at_25pct_of_daily_capital_even_with_ample_free_capital():
    risk = {"max_daily_capital": 80_000.0}
    budget = trade_budget(risk, free_capital=1_000_000.0, capital_used_today=0.0)
    assert budget == 20_000.0


def test_trade_budget_still_respects_free_capital_below_the_25pct_cap():
    risk = {"max_daily_capital": 80_000.0}
    budget = trade_budget(risk, free_capital=5_000.0, capital_used_today=0.0)
    assert budget == 5_000.0


def test_trade_budget_still_respects_remaining_daily_allowance_below_the_25pct_cap():
    risk = {"max_daily_capital": 80_000.0}
    budget = trade_budget(risk, free_capital=1_000_000.0, capital_used_today=75_000.0)
    assert budget == 5_000.0
