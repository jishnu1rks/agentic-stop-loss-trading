"""
Momentum Breakout Agent (Section 5.3): "Enters when price breaks above
N-day high with volume confirmation." Unlike Watchlist-Trigger, this
strategy discovers candidates across a whole universe rather than checking
a hand-picked list against hand-picked price bands.

strategy_params shape:
{
  "lookback_days": 20,
  "breakout_threshold_pct": 2.0,   # price must clear the N-day high by this %
  "volume_confirmation_multiplier": 1.0  # latest volume must be >= this * avg volume over lookback
}
Matches the example config in Section 5.2.
"""
from app.adapters.market_data.base import MarketDataSnapshot
from app.strategies.base import Signal, Strategy


class MomentumBreakoutStrategy(Strategy):
    def scan(
        self,
        universe: list[str],
        market_data: MarketDataSnapshot,
        params: dict,
    ) -> list[Signal]:
        breakout_threshold_pct = params.get("breakout_threshold_pct", 2.0)
        volume_multiplier = params.get("volume_confirmation_multiplier", 1.0)
        signals: list[Signal] = []

        for symbol in universe:
            price = market_data.prices.get(symbol)
            history = market_data.history.get(symbol)
            if price is None or not history or len(history) < 2:
                continue

            # N-day high excludes today's price so a symbol can't "break out"
            # against itself on the same bar it's being evaluated.
            prior_high = max(history[:-1])
            if prior_high <= 0:
                continue
            breakout_pct = (price - prior_high) / prior_high * 100
            if breakout_pct < breakout_threshold_pct:
                continue

            volumes = market_data.volumes.get(symbol)
            volume_confirmed = True
            volume_note = "volume data unavailable, confirmation skipped"
            if volumes and len(volumes) >= 2:
                avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
                latest_volume = volumes[-1]
                volume_confirmed = avg_volume > 0 and latest_volume >= avg_volume * volume_multiplier
                volume_note = (
                    f"volume {latest_volume:,.0f} vs avg {avg_volume:,.0f} "
                    f"({'confirmed' if volume_confirmed else 'not confirmed'})"
                )

            if not volume_confirmed:
                continue

            signals.append(
                Signal(
                    symbol=symbol,
                    direction="buy",
                    confidence=min(1.0, breakout_pct / (breakout_threshold_pct * 3)),
                    reason=(
                        f"price {price:g} is {breakout_pct:.1f}% above the "
                        f"{len(history)}-day prior high of {prior_high:g}; {volume_note}"
                    ),
                )
            )

        return signals
