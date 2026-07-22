from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ---- Agent config (Section 5.2) ----

# Stop-loss/target are always expressed as % of entry price (CMP at fill
# time), never a currency amount - bounding them here keeps a fat-fingered
# config (or an intentionally reckless one) from arming a trade with, say,
# a 50% stop-loss. 0.1% floor blocks an effectively-zero stop that would
# offer no real protection; 5% ceiling matches this system's risk profile
# for NSE large/mid-caps (Section 5).
PCT_LOWER_BOUND = 0.1
PCT_UPPER_BOUND = 5.0


class AgentRiskConfig(BaseModel):
    buy_stop_loss_pct: float = Field(ge=PCT_LOWER_BOUND, le=PCT_UPPER_BOUND)
    sell_stop_loss_pct: float = Field(ge=PCT_LOWER_BOUND, le=PCT_UPPER_BOUND)
    target_pct: float | None = Field(default=None, ge=PCT_LOWER_BOUND, le=PCT_UPPER_BOUND)
    max_concurrent_positions: int = Field(default=5, ge=1)
    max_daily_capital: float = Field(default=100_000.0, gt=0)


class AgentScheduleConfig(BaseModel):
    type: Literal["interval"] = "interval"
    interval_minutes: int = 5
    market_hours_only: bool = True


class ScreenerUniverseConfig(BaseModel):
    """Live NSE discovery instead of a hand-maintained symbol list (Section
    5.1 "screener" universe type) - see YFinanceMarketDataAdapter.get_trending_symbols."""
    sort_by: Literal["dayvolume", "percentchange"] = "dayvolume"
    limit: int = Field(default=15, ge=1, le=50)
    min_market_cap: float = Field(default=5_000_000_000, gt=0)


class AgentUniverseConfig(BaseModel):
    type: Literal["watchlist", "index", "screener"] = "watchlist"
    value: list[str] | str | None = None
    screener: ScreenerUniverseConfig | None = None

    @model_validator(mode="after")
    def _check_value(self) -> "AgentUniverseConfig":
        if self.type == "screener":
            if self.screener is None:
                self.screener = ScreenerUniverseConfig()
        elif not self.value:
            raise ValueError(f"universe.value is required for type '{self.type}'")
        return self


class AgentConfigIn(BaseModel):
    agent_id: str
    name: str
    active: bool = True
    universe: AgentUniverseConfig
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    # Recommend-only agents (llm_recommendation - Section 5.2's Recommending
    # agent) never size or protect a position themselves, so they carry no
    # risk config at all; every other strategy actually enters trades and
    # must have one.
    risk: AgentRiskConfig | None = None
    schedule: AgentScheduleConfig

    @model_validator(mode="after")
    def _check_llm_recommendation_prompt(self) -> "AgentConfigIn":
        if self.strategy == "llm_recommendation" and not (self.strategy_params.get("prompt") or "").strip():
            raise ValueError("strategy_params.prompt is required for the llm_recommendation strategy")
        return self

    @model_validator(mode="after")
    def _check_risk_required_for_trading_strategies(self) -> "AgentConfigIn":
        if self.strategy != "llm_recommendation" and self.risk is None:
            raise ValueError("risk is required for a strategy that places trades")
        return self


class AgentOut(BaseModel):
    agent_id: str
    name: str
    strategy: str
    config: dict[str, Any]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Trades (Section 6.1) ----

class TradeOut(BaseModel):
    trade_id: str
    agent_id: str | None
    stock_symbol: str
    direction: str
    quantity: int
    buy_price: float
    sell_price: float | None
    purchase_date: datetime
    sell_date: datetime | None
    stop_loss_pct: float
    stop_loss_price: float
    target_pct: float | None
    target_price: float | None
    exit_reason: str | None
    gross_profit: float | None
    charges: float | None
    tax: float | None
    net_profit: float | None
    status: str
    broker_order_id: str | None
    is_manual: bool

    model_config = {"from_attributes": True}


class ManualTradeIn(BaseModel):
    stock_symbol: str
    direction: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    stop_loss_pct: float | None = None
    target_pct: float | None = None


class ModifyProtectionIn(BaseModel):
    """Edit the stop-loss / target price levels on an open position."""
    stop_loss_price: float = Field(gt=0)
    target_price: float | None = Field(default=None, gt=0)
