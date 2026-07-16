from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- Agent config (Section 5.2) ----

class AgentRiskConfig(BaseModel):
    buy_stop_loss_pct: float
    sell_stop_loss_pct: float
    target_pct: float | None = None
    position_size_type: Literal["fixed_amount", "pct_capital"] = "fixed_amount"
    position_size_value: float
    max_concurrent_positions: int = 5
    max_daily_capital: float = 100_000.0


class AgentScheduleConfig(BaseModel):
    type: Literal["interval"] = "interval"
    interval_minutes: int = 5
    market_hours_only: bool = True


class AgentUniverseConfig(BaseModel):
    type: Literal["watchlist", "index"] = "watchlist"
    value: list[str] | str


class AgentConfigIn(BaseModel):
    agent_id: str
    name: str
    active: bool = True
    universe: AgentUniverseConfig
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    risk: AgentRiskConfig
    schedule: AgentScheduleConfig


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
