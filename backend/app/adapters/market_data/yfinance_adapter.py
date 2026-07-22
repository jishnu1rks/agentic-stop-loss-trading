from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

import yfinance as yf

from app.adapters.market_data.base import MarketDataAdapter, MarketDataSnapshot
from app.fundamentals import LARGE_CAP_FLOOR, MID_CAP_FLOOR

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Floor for the small-cap tier of get_tiered_trending_symbols, so a
# dayvolume-sorted "small cap" pull doesn't surface pure penny/illiquid
# junk (classify_cap_size itself has no floor below MID_CAP_FLOOR) -
# matches the min_market_cap already used elsewhere in this system's
# agent configs (e.g. the Execution agent's flat screener).
SMALL_CAP_SCREENER_FLOOR = 500 * 10_000_000


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

    def get_tiered_trending_symbols(
        self,
        large_count: int = 5,
        mid_count: int = 5,
        small_count: int = 5,
        sort_by: Literal["dayvolume", "percentchange"] = "dayvolume",
    ) -> list[str]:
        """Like get_trending_symbols, but pulls a fixed count from each
        market-cap tier instead of one flat top-N list - a dayvolume sort
        with a single min_market_cap floor otherwise skews almost entirely
        large-cap. Cap bands mirror app.fundamentals.classify_cap_size
        (LARGE_CAP_FLOOR/MID_CAP_FLOOR) so a symbol's tier here matches how
        it's labeled elsewhere (cap_size on recommendation cards). A tier
        returning fewer than requested (or zero) doesn't block the others -
        only an entirely empty combined result is treated as unavailable."""
        tiers: list[tuple[int, list]] = [
            (large_count, [yf.EquityQuery("gt", ["intradaymarketcap", LARGE_CAP_FLOOR])]),
            (
                mid_count,
                [
                    yf.EquityQuery("gt", ["intradaymarketcap", MID_CAP_FLOOR]),
                    yf.EquityQuery("lt", ["intradaymarketcap", LARGE_CAP_FLOOR]),
                ],
            ),
            (
                small_count,
                [
                    yf.EquityQuery("gt", ["intradaymarketcap", SMALL_CAP_SCREENER_FLOOR]),
                    yf.EquityQuery("lt", ["intradaymarketcap", MID_CAP_FLOOR]),
                ],
            ),
        ]

        symbols: list[str] = []
        for count, cap_clauses in tiers:
            if count <= 0:
                continue
            query = yf.EquityQuery("and", [yf.EquityQuery("eq", ["exchange", "NSI"]), *cap_clauses])
            try:
                result = yf.screen(query, count=count, sortField=sort_by, sortAsc=False)
            except Exception as exc:
                raise MarketDataUnavailableError(f"Screener request failed: {exc}") from exc
            # yfinance's `count` param is only a request, not a guarantee -
            # this version of the library returns a ~25-row page regardless
            # of a smaller count (same reason get_trending_symbols slices
            # with symbols[:limit] below) - so truncate per tier here too.
            tier_symbols = []
            for quote in result.get("quotes", []):
                symbol = quote.get("symbol")
                if symbol and symbol.endswith(".NS"):
                    tier_symbols.append(symbol[: -len(".NS")])
            symbols.extend(tier_symbols[:count])

        if not symbols:
            raise MarketDataUnavailableError("Screener returned no NSE symbols")
        return symbols

    def get_fundamentals(self, symbol: str) -> dict | None:
        """Pulls the subset of yf.Ticker(...).info that's reliably populated
        for NSE names: valuation (P/E, P/B, PEG), Debt/Equity, market cap,
        insider-holding % (the closest available proxy for promoter holding),
        and trailing revenue/earnings growth. ROE, ROCE, free cash flow,
        interest coverage, and promoter pledging/governance data are NOT
        reliably available from this source for Indian tickers and are
        deliberately left out here rather than reported as fake/stale data -
        app.fundamentals.score_fundamentals only scores what's present."""
        try:
            info = yf.Ticker(_to_yf_symbol(symbol)).info
        except Exception:
            return None
        if not info or info.get("marketCap") is None:
            return None
        return {
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "peg": info.get("pegRatio"),
            "debt_to_equity": info.get("debtToEquity"),
            "market_cap": info.get("marketCap"),
            "insider_holding_pct": info.get("heldPercentInsiders"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
        }
