"""
Watchlist-Trigger Agent (Section 5.3): simplest strategy - no technical
analysis. User supplies a fixed list of stocks with entry price bands;
agent enters when price crosses into the band, then manages exit purely
via GTT stop-loss/target (shared Section 4 flow).

strategy_params shape:
{
  "bands": {
    "RELIANCE": {"direction": "buy", "low": 2400, "high": 2450},
    "INFY": {"direction": "sell", "low": 1500, "high": 1550}
  }
}
"""
from app.adapters.market_data.base import MarketDataSnapshot
from app.strategies.base import Signal, Strategy


class WatchlistTriggerStrategy(Strategy):
    def scan(
        self,
        universe: list[str],
        market_data: MarketDataSnapshot,
        params: dict,
    ) -> list[Signal]:
        bands = params.get("bands", {})
        signals: list[Signal] = []

        for symbol in universe:
            band = bands.get(symbol)
            if band is None:
                continue
            price = market_data.prices.get(symbol)
            if price is None:
                continue

            low, high = band["low"], band["high"]
            if low <= price <= high:
                signals.append(
                    Signal(
                        symbol=symbol,
                        direction=band["direction"],
                        confidence=1.0,
                        reason=f"price {price} within entry band [{low}, {high}]",
                    )
                )

        return signals
