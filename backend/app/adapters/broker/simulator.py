"""
Phase 1 simulator: in-memory paper broker. No real orders are sent anywhere.
Implements the same interface a live Kite adapter will, so agent logic
never has to change when Phase 2 lands (Section 3.2).
"""
import uuid
from datetime import datetime, timezone

from app.adapters.broker.base import (
    BrokerAdapter,
    Direction,
    GttComparator,
    GttOrder,
    OrderFill,
)
from app.config import settings


class SimulatorBrokerAdapter(BrokerAdapter):
    def __init__(self):
        self._seen_client_order_ids: dict[str, OrderFill] = {}
        self._gtts: dict[str, GttOrder] = {}

    def _apply_slippage(self, price: float, direction: Direction) -> float:
        slip = settings.simulator_slippage_pct / 100.0
        # Fills are marginally worse than reference price, in the direction
        # that hurts the trader - matches real-world slippage risk (Section 9).
        return price * (1 + slip) if direction == "buy" else price * (1 - slip)

    def place_entry_order(
        self,
        client_order_id: str,
        symbol: str,
        direction: Direction,
        quantity: int,
        reference_price: float,
    ) -> OrderFill:
        if client_order_id in self._seen_client_order_ids:
            return self._seen_client_order_ids[client_order_id]  # idempotent replay

        fill = OrderFill(
            order_id=f"SIM-{uuid.uuid4().hex[:10]}",
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=round(self._apply_slippage(reference_price, direction), 2),
            timestamp=datetime.now(timezone.utc),
        )
        self._seen_client_order_ids[client_order_id] = fill
        return fill

    def place_gtt(
        self,
        client_order_id: str,
        symbol: str,
        direction: Direction,
        trigger_price: float,
        comparator: GttComparator,
        quantity: int,
        kind,
    ) -> GttOrder:
        existing = self._gtts.get(client_order_id)
        if existing is not None:
            return existing  # idempotent replay - no duplicate GTTs (Section 9)

        gtt = GttOrder(
            gtt_id=client_order_id,
            symbol=symbol,
            direction=direction,
            trigger_price=round(trigger_price, 2),
            comparator=comparator,
            quantity=quantity,
            kind=kind,
            status="pending",
        )
        self._gtts[gtt.gtt_id] = gtt
        return gtt

    def check_and_fill_gtts(self, current_prices: dict[str, float]) -> list[OrderFill]:
        fills = []
        for gtt in self._gtts.values():
            if gtt.status != "pending":
                continue
            price = current_prices.get(gtt.symbol)
            if price is None:
                continue
            triggered = (
                price <= gtt.trigger_price
                if gtt.comparator == "lte"
                else price >= gtt.trigger_price
            )
            if triggered:
                gtt.status = "triggered"
                fills.append(
                    OrderFill(
                        order_id=f"SIM-GTT-{uuid.uuid4().hex[:10]}",
                        symbol=gtt.symbol,
                        direction=gtt.direction,
                        quantity=gtt.quantity,
                        price=round(self._apply_slippage(price, gtt.direction), 2),
                        timestamp=datetime.now(timezone.utc),
                        source_gtt_id=gtt.gtt_id,
                    )
                )
        return fills

    def cancel_gtt(self, gtt_id: str) -> None:
        gtt = self._gtts.get(gtt_id)
        if gtt and gtt.status == "pending":
            gtt.status = "cancelled"

    def get_open_gtts_for_symbol(self, symbol: str) -> list[GttOrder]:
        return [g for g in self._gtts.values() if g.symbol == symbol and g.status == "pending"]
