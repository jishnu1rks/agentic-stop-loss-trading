from app.strategies.base import Strategy
from app.strategies.momentum_breakout import MomentumBreakoutStrategy
from app.strategies.watchlist_trigger import WatchlistTriggerStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "watchlist_trigger": WatchlistTriggerStrategy,
    "momentum_breakout": MomentumBreakoutStrategy,
}


def get_strategy(name: str) -> Strategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy '{name}'. Registered: {list(STRATEGY_REGISTRY)}"
        )
    return cls()
