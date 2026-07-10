from app.adapters.market_data.base import MarketDataSnapshot
from app.strategies.watchlist_trigger import WatchlistTriggerStrategy


def test_signal_fires_when_price_within_band():
    strategy = WatchlistTriggerStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2420.0}, history={})
    params = {"bands": {"RELIANCE": {"direction": "buy", "low": 2400, "high": 2450}}}

    signals = strategy.scan(["RELIANCE"], snapshot, params)

    assert len(signals) == 1
    assert signals[0].symbol == "RELIANCE"
    assert signals[0].direction == "buy"


def test_no_signal_when_price_outside_band():
    strategy = WatchlistTriggerStrategy()
    snapshot = MarketDataSnapshot(prices={"RELIANCE": 2500.0}, history={})
    params = {"bands": {"RELIANCE": {"direction": "buy", "low": 2400, "high": 2450}}}

    assert strategy.scan(["RELIANCE"], snapshot, params) == []


def test_symbol_without_a_band_is_ignored():
    strategy = WatchlistTriggerStrategy()
    snapshot = MarketDataSnapshot(prices={"TCS": 3500.0}, history={})
    assert strategy.scan(["TCS"], snapshot, {"bands": {}}) == []
