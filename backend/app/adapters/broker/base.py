"""
Broker Adapter interface (Section 3.1/3.2).

This is the seam the spec calls out explicitly: "The Broker Adapter and
Market Data Adapter are built as interchangeable interfaces from day one,
so switching from simulation to Kite Connect later requires no change to
agent logic." Every method here maps to something Kite Connect actually
exposes (place_order, place_gtt, modify/cancel, positions) so a future
KiteBrokerAdapter is a drop-in.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["buy", "sell"]
GttComparator = Literal["lte", "gte"]


@dataclass
class OrderFill:
    order_id: str
    symbol: str
    direction: Direction
    quantity: int
    price: float
    timestamp: datetime
    source_gtt_id: str | None = None  # set when this fill came from check_and_fill_gtts


@dataclass
class GttOrder:
    gtt_id: str
    symbol: str
    direction: Direction  # side the GTT will execute (opposite of entry direction)
    trigger_price: float
    comparator: GttComparator  # "lte" = triggers when price falls to/below; "gte" = rises to/above
    quantity: int
    kind: Literal["stop_loss", "target"]
    status: Literal["pending", "triggered", "cancelled"] = "pending"


class BrokerAdapter(ABC):
    """Every call takes a client_order_id so retries are idempotent (Section 9)."""

    @abstractmethod
    def place_entry_order(
        self,
        client_order_id: str,
        symbol: str,
        direction: Direction,
        quantity: int,
        reference_price: float,
    ) -> OrderFill:
        """Place a market entry order. reference_price is used by the
        simulator as the fill price; a live adapter would ignore it and
        return the exchange's actual fill."""

    @abstractmethod
    def place_gtt(
        self,
        client_order_id: str,
        symbol: str,
        direction: Direction,
        trigger_price: float,
        comparator: GttComparator,
        quantity: int,
        kind: Literal["stop_loss", "target"],
    ) -> GttOrder:
        """Place a GTT (Good Till Triggered) conditional order - the
        mechanism used for both stop-loss and target exits (Section 1, 4)."""

    @abstractmethod
    def check_and_fill_gtts(self, current_prices: dict[str, float]) -> list[OrderFill]:
        """Evaluate all pending GTTs against current prices; fill any that
        trigger and return their fills. Called once per monitor cycle."""

    @abstractmethod
    def cancel_gtt(self, gtt_id: str) -> None:
        """Cancel a pending GTT (e.g. the target order once stop-loss fires,
        or vice versa - only one side of a bracket should remain live)."""

    @abstractmethod
    def get_open_gtts_for_symbol(self, symbol: str) -> list[GttOrder]:
        ...
