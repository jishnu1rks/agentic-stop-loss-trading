from app.adapters.market_data.base import MarketDataSnapshot
from app.strategies.momentum_breakout import MomentumBreakoutStrategy


def test_signal_fires_on_breakout_with_volume_confirmation():
    strategy = MomentumBreakoutStrategy()
    snapshot = MarketDataSnapshot(
        prices={"FOO": 110.0},
        history={"FOO": [100, 101, 100, 99, 100]},  # prior high = 101
        volumes={"FOO": [1000, 1000, 1000, 1000, 2000]},  # latest > avg of prior
    )
    signals = strategy.scan(["FOO"], snapshot, {"breakout_threshold_pct": 2.0})

    assert len(signals) == 1
    assert signals[0].symbol == "FOO"
    assert signals[0].direction == "buy"


def test_no_signal_when_price_has_not_broken_out():
    strategy = MomentumBreakoutStrategy()
    snapshot = MarketDataSnapshot(
        prices={"FOO": 101.0},
        history={"FOO": [100, 101, 100, 99, 100]},  # prior high = 101, price barely below/at it
        volumes={"FOO": [1000, 1000, 1000, 1000, 2000]},
    )
    signals = strategy.scan(["FOO"], snapshot, {"breakout_threshold_pct": 2.0})

    assert signals == []


def test_no_signal_without_volume_confirmation():
    strategy = MomentumBreakoutStrategy()
    snapshot = MarketDataSnapshot(
        prices={"FOO": 110.0},
        history={"FOO": [100, 101, 100, 99, 100]},
        volumes={"FOO": [1000, 1000, 1000, 1000, 500]},  # latest volume below average - no confirmation
    )
    signals = strategy.scan(["FOO"], snapshot, {"breakout_threshold_pct": 2.0})

    assert signals == []


def test_signal_fires_when_volume_data_missing():
    strategy = MomentumBreakoutStrategy()
    snapshot = MarketDataSnapshot(
        prices={"FOO": 110.0},
        history={"FOO": [100, 101, 100, 99, 100]},
        volumes={},  # no volume data at all - confirmation is skipped, not treated as a failure
    )
    signals = strategy.scan(["FOO"], snapshot, {"breakout_threshold_pct": 2.0})

    assert len(signals) == 1
    assert "volume data unavailable" in signals[0].reason


def test_symbol_missing_from_snapshot_is_skipped():
    strategy = MomentumBreakoutStrategy()
    snapshot = MarketDataSnapshot(prices={}, history={}, volumes={})
    assert strategy.scan(["FOO"], snapshot, {}) == []
