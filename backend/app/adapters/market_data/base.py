"""Market Data Adapter interface (Section 3.1/3.2) - interchangeable with a
future Kite Connect (or other) data source without touching agent logic."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


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

    @abstractmethod
    def get_trending_symbols(
        self,
        sort_by: Literal["dayvolume", "percentchange"] = "dayvolume",
        limit: int = 15,
        min_market_cap: float = 5_000_000_000,
    ) -> list[str]:
        """Discover a live universe (e.g. today's most-active or biggest
        movers) rather than relying on a hand-maintained watchlist/index -
        the "screener" universe type (Section 5.1)."""

    @abstractmethod
    def get_fundamentals(self, symbol: str) -> dict | None:
        """Point-in-time valuation/financial-health snapshot for one symbol,
        used to apply a standard recommendability screen to a "screener"
        universe (see app.fundamentals). Returns None if nothing usable came
        back for this symbol - callers must treat that as "unknown", not as
        a failing score."""
