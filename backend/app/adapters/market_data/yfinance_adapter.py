from datetime import datetime, time
from typing import Literal
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

    def get_trending_symbols(
        self,
        sort_by: Literal["dayvolume", "percentchange"] = "dayvolume",
        limit: int = 15,
        min_market_cap: float = 5_000_000_000,
    ) -> list[str]:
        """Live NSE universe discovery via Yahoo's equity screener (Section 5.1
        "screener" universe type) - an alternative to a hand-maintained
        watchlist/index list. sort_by="dayvolume" surfaces today's most-active
        names, "percentchange" surfaces today's biggest movers. min_market_cap
        filters out illiquid/penny names that would otherwise dominate a
        percentchange sort. This hits an unofficial Yahoo endpoint (same as
        the rest of yfinance) - no SLA, and it can change shape without
        notice, so failures are treated the same as any other market-data
        outage rather than allowed to crash the scan."""
        query = yf.EquityQuery(
            "and",
            [
                yf.EquityQuery("eq", ["exchange", "NSI"]),
                yf.EquityQuery("gt", ["intradaymarketcap", min_market_cap]),
            ],
        )
        try:
            result = yf.screen(query, count=limit, sortField=sort_by, sortAsc=False)
        except Exception as exc:
            raise MarketDataUnavailableError(f"Screener request failed: {exc}") from exc

        quotes = result.get("quotes", [])
        if not quotes:
            raise MarketDataUnavailableError("Screener returned no NSE symbols")

        symbols = []
        for quote in quotes:
            symbol = quote.get("symbol")
            if symbol and symbol.endswith(".NS"):
                symbols.append(symbol[: -len(".NS")])
        return symbols[:limit]
