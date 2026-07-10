from datetime import datetime, time
from zoneinfo import ZoneInfo

import yfinance as yf

from app.adapters.market_data.base import MarketDataAdapter, MarketDataSnapshot

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


class MarketDataUnavailableError(Exception):
    """Raised when no requested symbol returned usable data. Section 9
    fail-safe: agents must pause on this, never trade on stale data."""


def _to_yf_symbol(symbol: str) -> str:
    return symbol if "." in symbol else f"{symbol}.NS"


class YFinanceMarketDataAdapter(MarketDataAdapter):
    def get_snapshot(self, symbols: list[str], lookback_days: int = 20) -> MarketDataSnapshot:
        """Batch-fetches all symbols in one request (yf.download) rather
        than one HTTP round-trip per symbol - the difference between ~1s
        and ~30s+ for a 50-symbol universe scan, and far less likely to
        trip Yahoo's rate limiting. A symbol with no usable data is
        skipped rather than aborting the whole batch; only raises if
        *nothing* came back (covers the single-symbol call case too)."""
        yf_symbols = [_to_yf_symbol(s) for s in symbols]
        try:
            data = yf.download(
                yf_symbols,
                period=f"{max(lookback_days, 5)}d",
                interval="1d",
                group_by="ticker",
                progress=False,
                threads=True,
                auto_adjust=True,
            )
        except Exception as exc:
            raise MarketDataUnavailableError(f"Batch download failed: {exc}") from exc

        prices: dict[str, float] = {}
        history: dict[str, list[float]] = {}
        volumes: dict[str, list[float]] = {}

        for symbol, yf_symbol in zip(symbols, yf_symbols):
            try:
                df = data[yf_symbol]
                closes = df["Close"].dropna()
                if closes.empty:
                    continue
                prices[symbol] = float(closes.iloc[-1])
                history[symbol] = [float(c) for c in closes.tolist()]
                vols = df["Volume"].dropna()
                if not vols.empty:
                    volumes[symbol] = [float(v) for v in vols.tolist()]
            except (KeyError, IndexError):
                continue  # this symbol had no usable data in the batch response

        if not prices:
            raise MarketDataUnavailableError(f"No usable data returned for {symbols}")

        return MarketDataSnapshot(prices=prices, history=history, volumes=volumes)

    def is_market_open(self) -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:  # Sat/Sun
            return False
        return MARKET_OPEN <= now.time() <= MARKET_CLOSE
