from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.market_data import get_market_data_adapter
from app.adapters.market_data.yfinance_adapter import MarketDataUnavailableError
from app.agent_runtime import close_trade_manually, enter_position, get_capital_summary
from app.db import get_db
from app.models import Trade
from app.schemas import ManualTradeIn, TradeOut

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeOut])
def list_trades(
    agent_id: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    exit_reason: str | None = None,
    is_manual: bool | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Trade)
    if agent_id is not None:
        query = query.filter(Trade.agent_id == agent_id)
    if status is not None:
        query = query.filter(Trade.status == status)
    if direction is not None:
        query = query.filter(Trade.direction == direction)
    if exit_reason is not None:
        query = query.filter(Trade.exit_reason == exit_reason)
    if is_manual is not None:
        query = query.filter(Trade.is_manual == is_manual)
    return query.order_by(Trade.purchase_date.desc()).all()


@router.get("/{trade_id}", response_model=TradeOut)
def get_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
    if trade is None:
        raise HTTPException(404, "Trade not found")
    return trade


@router.post("/manual", response_model=TradeOut, status_code=201)
def place_manual_trade(payload: ManualTradeIn, db: Session = Depends(get_db)):
    """Section 7.7: manual Buy/Sell control, same Broker Adapter as agents,
    tagged is_manual=True rather than attributed to any agent_id."""
    try:
        snapshot = get_market_data_adapter().get_snapshot([payload.stock_symbol], lookback_days=1)
    except MarketDataUnavailableError as exc:
        raise HTTPException(503, f"Market data unavailable: {exc}") from exc

    price = snapshot.prices.get(payload.stock_symbol)
    if price is None:
        raise HTTPException(422, f"No price available for {payload.stock_symbol}")

    trade_value = price * payload.quantity
    free_capital = get_capital_summary(db)["free_capital"]
    if trade_value > free_capital:
        raise HTTPException(
            422,
            f"Insufficient free capital: this trade needs ₹{trade_value:,.2f} but only "
            f"₹{free_capital:,.2f} is free.",
        )

    trade = enter_position(
        db,
        agent_id=None,
        symbol=payload.stock_symbol,
        direction=payload.direction,
        quantity=payload.quantity,
        ref_price=price,
        buy_stop_loss_pct=payload.stop_loss_pct if payload.direction == "buy" else None,
        sell_stop_loss_pct=payload.stop_loss_pct if payload.direction == "sell" else None,
        target_pct=payload.target_pct,
        is_manual=True,
    )
    return trade


@router.post("/{trade_id}/close", response_model=TradeOut)
def close_trade_early(trade_id: str, db: Session = Depends(get_db)):
    """Section 7.7: let the user close a position early, independent of
    any agent's logic or GTT trigger."""
    trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
    if trade is None:
        raise HTTPException(404, "Trade not found")
    if trade.status != "open":
        raise HTTPException(400, f"Trade is already {trade.status}")

    try:
        snapshot = get_market_data_adapter().get_snapshot([trade.stock_symbol], lookback_days=1)
    except MarketDataUnavailableError as exc:
        raise HTTPException(503, f"Market data unavailable: {exc}") from exc

    price = snapshot.prices.get(trade.stock_symbol)
    if price is None:
        raise HTTPException(422, f"No price available for {trade.stock_symbol}")

    close_trade_manually(db, trade, price)
    db.refresh(trade)
    return trade
