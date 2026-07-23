import functools
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.adapters.market_data import get_market_data_adapter
from app.adapters.market_data.yfinance_adapter import IST, MarketDataUnavailableError
from app.agent_runtime import (
    close_trade_manually,
    enter_position,
    estimate_trade_charges,
    get_capital_summary,
    get_open_positions_pnl,
    modify_protection,
)
from app.config import settings
from app.db import get_db
from app.models import Trade
from app.schemas import ManualTradeIn, ModifyProtectionIn, TradeOut

router = APIRouter(prefix="/trades", tags=["trades"])

# Whitelist for sort_by - avoids arbitrary getattr() access from a query param.
_SORTABLE_FIELDS = {
    "purchase_date", "sell_date", "stock_symbol", "direction", "quantity",
    "buy_price", "sell_price", "stop_loss_price", "target_price",
    "gross_profit", "net_profit", "charges", "tax", "status",
}


def _period_range(period: str, now: datetime) -> tuple[datetime, datetime] | None:
    """Calendar-bucketed IST range - mirrors the frontend's periodRange()
    (TradeLogTable.tsx) so server-side filtering agrees with what the
    History table used to compute client-side."""
    if period == "all":
        return None
    ist_now = now.astimezone(IST)
    if period == "today":
        start = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if period == "week":
        start = (ist_now - timedelta(days=ist_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)
    if period == "month":
        start = ist_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, next_month
    if period == "year":
        start = ist_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, start.replace(year=start.year + 1)
    raise HTTPException(422, f"Unknown period '{period}'")


def _in_period(trade: Trade, range_: tuple[datetime, datetime] | None) -> bool:
    if range_ is None:
        return True
    date = trade.sell_date or trade.purchase_date
    if date is None:
        return False
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return range_[0] <= date.astimezone(IST) < range_[1]


def _filtered_trades(
    db: Session,
    agent_id: str | None,
    status: str | None,
    direction: str | None,
    exit_reason: str | None,
    is_manual: bool | None,
    period: str,
) -> list[Trade]:
    """Shared by list_trades and trade_stats - filters done here rather
    than at the SQL level intentionally match the existing pandas-based
    dashboard.py endpoints' style (compare loaded Python datetimes, not a
    SQL-level tz comparison - SQLite here doesn't reliably round-trip
    tzinfo, same reason LlmSignalCache defensively re-attaches it)."""
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

    range_ = _period_range(period, datetime.now(timezone.utc))
    return [t for t in query.all() if _in_period(t, range_)]


def _capital_as_of(db: Session, before: datetime | None) -> float:
    """Account equity at a point in time (or right now, if before=None):
    starting capital plus realized P&L from every trade closed strictly
    before that point. Always account-wide (every closed trade, regardless
    of any agent_id/status/etc. filter on the calling endpoint) - matches
    get_capital_summary's "capital is a real constraint on the whole
    account" convention."""
    closed = db.query(Trade).filter(Trade.status == "closed").all()
    realized = 0.0
    for t in closed:
        sell_date = t.sell_date
        if sell_date is None:
            continue
        if sell_date.tzinfo is None:
            sell_date = sell_date.replace(tzinfo=timezone.utc)
        if before is None or sell_date < before:
            realized += t.net_profit or 0
    return round(settings.account_starting_capital + realized, 2)


def _compare(a: Trade, b: Trade, sort_by: str, sort_dir: str) -> int:
    """Nulls always sort last regardless of direction - mirrors the
    frontend's previous client-side sort comparator exactly."""
    av, bv = getattr(a, sort_by), getattr(b, sort_by)
    if av is None and bv is None:
        return 0
    if av is None:
        return 1
    if bv is None:
        return -1
    if av < bv:
        return -1 if sort_dir == "asc" else 1
    if av > bv:
        return 1 if sort_dir == "asc" else -1
    return 0


@router.get("", response_model=list[TradeOut])
def list_trades(
    agent_id: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    exit_reason: str | None = None,
    is_manual: bool | None = None,
    period: str = "all",
    sort_by: str = "purchase_date",
    sort_dir: str = "desc",
    limit: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """period/sort_by/sort_dir/limit/offset are all optional and backward
    compatible - a caller that doesn't pass them (e.g. TradeToasts.tsx's
    bare listTrades()) gets exactly the original behavior: every matching
    trade, sorted by purchase_date desc, unpaginated."""
    if sort_by not in _SORTABLE_FIELDS:
        raise HTTPException(422, f"Cannot sort by '{sort_by}'")

    trades = _filtered_trades(db, agent_id, status, direction, exit_reason, is_manual, period)
    trades.sort(key=functools.cmp_to_key(lambda a, b: _compare(a, b, sort_by, sort_dir)))

    if limit is not None:
        return trades[offset : offset + limit]
    return trades[offset:] if offset else trades


@router.get("/stats")
def trade_stats(
    agent_id: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    exit_reason: str | None = None,
    is_manual: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
):
    """Aggregates over the whole period-filtered set, independent of
    list_trades' pagination - the History page's stat cards read from here
    instead of summing a client-side trade array, since that array is no
    longer guaranteed to hold every matching trade once paginated.

    Also carries the capital card's numbers, scoped to the same period:
    capital_at_period_start is account equity right before the period began
    (settings.account_starting_capital itself when period="all", since
    there's no earlier boundary to net realized P&L against), current_capital
    is equity right now regardless of period (there's only one "now"), and
    first_trade_date is the earliest trade *within* this period - not the
    account's all-time first trade - so it tracks whichever window is
    selected (e.g. "today" shows today's first trade, if any)."""
    trades = _filtered_trades(db, agent_id, status, direction, exit_reason, is_manual, period)
    count = len(trades)
    wins = sum(1 for t in trades if (t.net_profit or 0) > 0)

    range_ = _period_range(period, datetime.now(timezone.utc))
    capital_at_period_start = (
        round(settings.account_starting_capital, 2) if range_ is None else _capital_as_of(db, range_[0])
    )
    first_trade_date = min((t.purchase_date for t in trades), default=None)

    return {
        "count": count,
        "gross_pnl": round(sum(t.gross_profit or 0 for t in trades), 2),
        "net_pnl": round(sum(t.net_profit or 0 for t in trades), 2),
        "charges": round(sum(t.charges or 0 for t in trades), 2),
        "tax": round(sum(t.tax or 0 for t in trades), 2),
        "win_rate": round(wins / count * 100, 2) if count else 0.0,
        "capital_at_period_start": capital_at_period_start,
        "current_capital": _capital_as_of(db, None),
        "first_trade_date": first_trade_date,
    }


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
