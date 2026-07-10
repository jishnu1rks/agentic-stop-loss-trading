from app.config import settings
from app.adapters.market_data.base import MarketDataAdapter
from app.adapters.market_data.yfinance_adapter import YFinanceMarketDataAdapter

_instance: MarketDataAdapter | None = None


def get_market_data_adapter() -> MarketDataAdapter:
    global _instance
    if _instance is not None:
        return _instance
    if settings.market_data_provider == "yfinance":
        _instance = YFinanceMarketDataAdapter()
    elif settings.market_data_provider == "kite":
        raise NotImplementedError(
            "Kite market data adapter is a Phase 2 stub - not implemented yet. "
            "Set MARKET_DATA_PROVIDER=yfinance."
        )
    else:
        raise ValueError(f"Unknown market_data_provider: {settings.market_data_provider}")
    return _instance
