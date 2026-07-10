"""Market Data Adapter interface (Section 3.1/3.2) - interchangeable with a
future Kite Connect (or other) data source without touching agent logic."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MarketDataSnapshot:
    """Point-in-time prices for a set of symbols, plus enough recent history
    for strategies that need it (e.g. Momentum Breakout's N-day high and
    volume confirmation). A symbol missing from `prices` means its data
    couldn't be fetched - callers should skip it, not treat it as zero."""
    prices: dict[str, float]
    history: dict[str, list[float]]  # symbol -> recent daily closes, oldest first
    volumes: dict[str, list[float]] = field(default_factory=dict)  # symbol -> recent daily volumes, oldest first


class MarketDataAdapter(ABC):
    @abstractmethod
    def get_snapshot(self, symbols: list[str], lookback_days: int = 20) -> MarketDataSnapshot:
        ...

    @abstractmethod
    def is_market_open(self) -> bool:
        ...
