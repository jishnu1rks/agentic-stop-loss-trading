"""
Strategy interface (Section 5.3) - the pluggable stock-selection seam.
Every strategy module shares the same downstream flow (entry + GTT +
logging, Section 4); a new agent type only needs a new scan() implementation.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from app.adapters.market_data.base import MarketDataSnapshot


@dataclass
class Signal:
    symbol: str
    direction: Literal["buy", "sell"]
    confidence: float  # 0-1
    reason: str


class Strategy(ABC):
    @abstractmethod
    def scan(
        self,
        universe: list[str],
        market_data: MarketDataSnapshot,
        params: dict,
    ) -> list[Signal]:
        """Return entry signals for symbols currently meeting this
        strategy's criteria. Must not raise on a single bad symbol - skip
        and let the caller log it instead."""
