from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.market_data import get_market_data_adapter
from app.adapters.market_data.yfinance_adapter import MarketDataUnavailableError
from app.agent_runtime import (
    close_trade_manually,
    enter_position,
    estimate_trade_charges,
    get_capital_summary,
    get_open_positions_pnl,
    modify_protection,
)
from app.db import get_db
from app.models import Trade
from app.schemas import ManualTradeIn, ModifyProtectionIn, TradeOut

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


@router.get("/open/pnl")
def open_positions_pnl(db: Session = Depends(get_db)):
    """Live mark-to-market for every open trade, keyed by trade_id - see
    agent_runtime.get_open_positions_pnl. Separate from the main trade
    listing since it needs a live market data fetch, not just a DB read."""
    return get_open_positions_pnl(db)


@router.get("/quote/{symbol}")
def get_quote(symbol: str):
    """Live current price for a ticker, used by the Add Trade popup so the
    user sees a price before committing to a quantity/stop-loss."""
    sym = symbol.strip().upper()
    try:
        snapshot = get_market_data_adapter().get_snapshot([sym], lookback_days=1)
    except MarketDataUnavailableError as exc:
        raise HTTPException(503, f"Market data unavailable: {exc}") from exc

    price = snapshot.prices.get(sym)
    if price is None:
        raise HTTPException(422, f"No price available for {sym}")
    return {"symbol": sym, "price": round(price, 2)}


@router.get("/{trade_id}/charges")
def trade_charges(trade_id: str, db: Session = Depends(get_db)):
    """Itemized charges/tax breakdown for the Net P&L popup - see
    agent_runtime.estimate_trade_charges for closed-vs-open semantics."""
    trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
    if trade is None:
        raise HTTPException(404, "Trade not found")

    if trade.status == "closed":
        if trade.sell_price is None:
            raise HTTPException(400, "Closed trade is missing a sell price")
        return estimate_trade_charges(trade, trade.sell_price)

    try:
        snapshot = get_market_data_adapter().get_snapshot([trade.stock_symbol], lookback_days=1)
    except MarketDataUnavailableError as exc:
        raise HTTPException(503, f"Market data unavailable: {exc}") from exc

    price = snapshot.prices.get(trade.stock_symbol)
    if price is None:
        raise HTTPException(422, f"No price available for {trade.stock_symbol}")
    return estimate_trade_charges(trade, price)


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


@router.patch("/{trade_id}/protection", response_model=TradeOut)
def edit_protection(trade_id: str, payload: ModifyProtectionIn, db: Session = Depends(get_db)):
    """Edit the stop-loss / target levels on an open position - cancels the
    old GTT bracket and arms a new one at the given prices (Section 4
    'Protect')."""
    trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
    if trade is None:
        raise HTTPException(404, "Trade not found")
    if trade.status != "open":
        raise HTTPException(400, f"Trade is already {trade.status}")

    # Direction-consistency guard: a valid bracket must straddle the entry
    # the right way round, otherwise a GTT would fire the instant it's armed.
    if trade.direction == "buy":
        if payload.stop_loss_price >= trade.buy_price:
            raise HTTPException(422, f"For a long position, stop-loss (₹{payload.stop_loss_price}) must be below the buy price (₹{trade.buy_price}).")
        if payload.target_price is not None and payload.target_price <= trade.buy_price:
            raise HTTPException(422, f"For a long position, target (₹{payload.target_price}) must be above the buy price (₹{trade.buy_price}).")
    else:
        if payload.stop_loss_price <= trade.buy_price:
            raise HTTPException(422, f"For a short position, stop-loss (₹{payload.stop_loss_price}) must be above the entry price (₹{trade.buy_price}).")
        if payload.target_price is not None and payload.target_price >= trade.buy_price:
            raise HTTPException(422, f"For a short position, target (₹{payload.target_price}) must be below the entry price (₹{trade.buy_price}).")

    modify_protection(db, trade, payload.stop_loss_price, payload.target_price)
    db.refresh(trade)
    return trade
