"""
Core trading flow (Section 4): Scan -> Signal -> Entry -> Protect -> Monitor
-> Exit -> Log -> Report. Shared by every strategy module (Section 5.3) and
by manual trades (Section 7.7), which go through the same Broker Adapter so
simulation vs. live behaviour stays consistent.
"""
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters.broker import get_broker_adapter
from app.adapters.broker.base import Direction
from app.adapters.market_data import get_market_data_adapter
from app.adapters.market_data.yfinance_adapter import MarketDataUnavailableError
from app.charges import compute_charges
from app.config import settings
from app.models import Agent, AgentLog, Trade
from app.strategies import get_strategy
from app.tax import estimate_tax


def _log(db: Session, agent_id: str, symbol: str | None, decision: str, reason: str) -> None:
    db.add(AgentLog(agent_id=agent_id, symbol=symbol, decision=decision, reason=reason))


# ---- Stop-loss direction logic (Section 4.1) ----

def stop_loss_price(direction: Direction, entry_price: float, stop_loss_pct: float) -> float:
    if direction == "buy":
        return round(entry_price * (1 - stop_loss_pct / 100), 2)
    return round(entry_price * (1 + stop_loss_pct / 100), 2)


def target_price(direction: Direction, entry_price: float, target_pct: float) -> float:
    if direction == "buy":
        return round(entry_price * (1 + target_pct / 100), 2)
    return round(entry_price * (1 - target_pct / 100), 2)


def exit_direction(entry_direction: Direction) -> Direction:
    """The GTT that protects a position trades the opposite side."""
    return "sell" if entry_direction == "buy" else "buy"


def position_size(risk: dict, price: float) -> int:
    if risk["position_size_type"] == "fixed_amount":
        return max(int(risk["position_size_value"] // price), 0)
    if risk["position_size_type"] == "pct_capital":
        budget = risk["max_daily_capital"] * (risk["position_size_value"] / 100)
        return max(int(budget // price), 0)
    raise ValueError(f"Unknown position_size_type: {risk['position_size_type']}")


def _open_position_count(db: Session, agent_id: str) -> int:
    return (
        db.query(func.count(Trade.trade_id))
        .filter(Trade.agent_id == agent_id, Trade.status == "open")
        .scalar()
        or 0
    )


def _capital_committed_today(db: Session, agent_id: str) -> float:
    today = datetime.now(timezone.utc).date()
    rows = (
        db.query(Trade.buy_price, Trade.quantity, Trade.direction)
        .filter(Trade.agent_id == agent_id, func.date(Trade.purchase_date) == str(today))
        .all()
    )
    return sum(r.buy_price * r.quantity for r in rows)


def _open_symbols(db: Session, agent_id: str) -> set[str]:
    rows = (
        db.query(Trade.stock_symbol)
        .filter(Trade.agent_id == agent_id, Trade.status == "open")
        .all()
    )
    return {r.stock_symbol for r in rows}


def get_capital_summary(db: Session) -> dict:
    """Account-wide capital tracking: a single static pool (Section 9-style
    hard constraint), shared across every agent and manual trades - not a
    per-agent allowance. Computed fresh from the trades table each call
    rather than a mutable running balance, so there's no ledger to drift
    out of sync or double-deduct."""
    open_trades = db.query(Trade.buy_price, Trade.quantity).filter(Trade.status == "open").all()
    capital_deployed = sum(t.buy_price * t.quantity for t in open_trades)

    realized_pnl = (
        db.query(func.coalesce(func.sum(Trade.net_profit), 0.0)).filter(Trade.status == "closed").scalar()
    )

    starting_capital = settings.account_starting_capital
    free_capital = starting_capital + realized_pnl - capital_deployed

    return {
        "starting_capital": round(starting_capital, 2),
        "capital_deployed": round(capital_deployed, 2),
        "realized_pnl": round(realized_pnl, 2),
        "free_capital": round(free_capital, 2),
    }


def get_open_positions_pnl(db: Session) -> dict[str, dict]:
    """Live mark-to-market for every open trade: current price, unrealized
    P&L (before charges/tax - those only get finalized on exit, see
    close_trade), and a 0-100 "heading" score showing where the current
    price sits between the stop-loss and target (0 = at stop-loss, 100 =
    at target). Keyed by trade_id so the frontend can merge it onto the
    trade rows it already has, rather than a duplicate trade listing.
    Best-effort per symbol - a quote that fails to fetch just leaves that
    trade out of the result rather than failing the batch."""
    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    if not open_trades:
        return {}

    symbols = list({t.stock_symbol for t in open_trades})
    try:
        snapshot = get_market_data_adapter().get_snapshot(symbols, lookback_days=1)
    except MarketDataUnavailableError:
        return {}

    result: dict[str, dict] = {}
    for trade in open_trades:
        price = snapshot.prices.get(trade.stock_symbol)
        if price is None:
            continue

        if trade.direction == "buy":
            unrealized_pnl = (price - trade.buy_price) * trade.quantity
        else:
            unrealized_pnl = (trade.buy_price - price) * trade.quantity
        unrealized_pnl_pct = round(unrealized_pnl / (trade.buy_price * trade.quantity) * 100, 2)

        heading_pct = None
        if trade.target_price:
            span = (
                trade.target_price - trade.stop_loss_price
                if trade.direction == "buy"
                else trade.stop_loss_price - trade.target_price
            )
            if span != 0:
                progress = (
                    (price - trade.stop_loss_price) / span
                    if trade.direction == "buy"
                    else (trade.stop_loss_price - price) / span
                )
                heading_pct = round(min(100.0, max(0.0, progress * 100)), 1)

        result[trade.trade_id] = {
            "current_price": round(price, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "heading_pct": heading_pct,
        }
    return result


def _band_proximity_pct(price: float, low: float, high: float) -> float:
    """How close price is to entering [low, high], as a 0-100 score. This is
    a plain distance heuristic, not a technical/predictive confidence score -
    the Watchlist-Trigger strategy has no technical analysis (Section 5.3),
    so a fabricated confidence % would misrepresent what it actually does."""
    if low <= price <= high:
        return 100.0
    distance_pct = (low - price) / low * 100 if price < low else (price - high) / high * 100
    return round(max(0.0, 100 - distance_pct * 20), 1)


def build_watchlist_recommendations(db: Session, agent: Agent) -> list[dict]:
    """Live, per-symbol trade-idea cards for a watchlist_trigger agent's
    universe: current price, entry band, computed target/stop-loss, position
    size, and a plain-language rationale - not a persisted signal, just
    today's read of the agent's own configured criteria. Best-effort per
    symbol so one bad quote doesn't blank the whole list."""
    market_data_adapter = get_market_data_adapter()
    config = agent.config
    bands = config.get("strategy_params", {}).get("bands", {})
    risk = config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)

    recommendations = []
    for symbol, band in bands.items():
        try:
            snapshot = market_data_adapter.get_snapshot([symbol], lookback_days=1)
        except MarketDataUnavailableError as exc:
            recommendations.append({"symbol": symbol, "unavailable": True, "reason": str(exc)})
            continue

        cmp = snapshot.prices.get(symbol)
        if cmp is None:
            recommendations.append({"symbol": symbol, "unavailable": True, "reason": "no price returned"})
            continue

        direction = band["direction"]
        low, high = band["low"], band["high"]
        in_band = low <= cmp <= high

        sl_price = stop_loss_price(direction, cmp, risk["buy_stop_loss_pct"] if direction == "buy" else risk["sell_stop_loss_pct"])
        tp_price = target_price(direction, cmp, risk["target_pct"]) if risk.get("target_pct") else None
        upside_pct = None
        if tp_price is not None:
            upside_pct = round(
                (tp_price - cmp) / cmp * 100 if direction == "buy" else (cmp - tp_price) / cmp * 100, 2
            )

        if in_band:
            rationale = f"Price ₹{cmp:g} is within the entry band ₹{low:g}–₹{high:g} - would enter now."
        elif cmp < low:
            rationale = f"Price ₹{cmp:g} is {(low - cmp) / low * 100:.1f}% below the entry band low of ₹{low:g}."
        else:
            rationale = f"Price ₹{cmp:g} is {(cmp - high) / high * 100:.1f}% above the entry band high of ₹{high:g}."

        recommendations.append(
            {
                "symbol": symbol,
                "unavailable": False,
                "direction": direction,
                "cmp": cmp,
                "entry_low": low,
                "entry_high": high,
                "stop_loss_price": sl_price,
                "target_price": tp_price,
                "upside_pct": upside_pct,
                "quantity": position_size(risk, cmp),
                "in_band": in_band,
                "proximity_pct": _band_proximity_pct(cmp, low, high),
                "already_open": symbol in open_symbols,
                "rationale": rationale,
            }
        )
    return recommendations


def build_momentum_recommendations(db: Session, agent: Agent, top_n: int = 10) -> list[dict]:
    """Live trade-idea cards for a momentum_breakout agent: scans its whole
    universe (e.g. NIFTY50 - Section 5.2's own example), ranks every symbol
    by how far price is above its N-day prior high, and returns the top N.
    Not every card in the list is necessarily a live signal right now - only
    ones flagged in_signal=True have actually cleared the breakout threshold
    with volume confirmation; the rest are the closest candidates, labeled
    as such, rather than padding out to N with fabricated buy calls."""
    market_data_adapter = get_market_data_adapter()
    config = agent.config
    universe_cfg = config["universe"]
    universe = universe_cfg["value"] if isinstance(universe_cfg["value"], list) else [universe_cfg["value"]]
    strategy_params = config.get("strategy_params", {})
    lookback_days = strategy_params.get("lookback_days", 20)
    breakout_threshold_pct = strategy_params.get("breakout_threshold_pct", 2.0)
    volume_multiplier = strategy_params.get("volume_confirmation_multiplier", 1.0)
    risk = config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)

    snapshot = market_data_adapter.get_snapshot(universe, lookback_days=lookback_days)

    candidates = []
    for symbol in universe:
        price = snapshot.prices.get(symbol)
        history = snapshot.history.get(symbol)
        if price is None or not history or len(history) < 2:
            continue
        prior_high = max(history[:-1])
        if prior_high <= 0:
            continue
        breakout_pct = round((price - prior_high) / prior_high * 100, 2)

        volumes = snapshot.volumes.get(symbol)
        volume_confirmed = True
        volume_note = "volume data unavailable, confirmation skipped"
        if volumes and len(volumes) >= 2:
            avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
            latest_volume = volumes[-1]
            volume_confirmed = avg_volume > 0 and latest_volume >= avg_volume * volume_multiplier
            volume_note = f"volume {latest_volume:,.0f} vs {lookback_days}d avg {avg_volume:,.0f}"

        in_signal = breakout_pct >= breakout_threshold_pct and volume_confirmed

        sl_price = stop_loss_price("buy", price, risk["buy_stop_loss_pct"])
        tp_price = target_price("buy", price, risk["target_pct"]) if risk.get("target_pct") else None
        upside_pct = round((tp_price - price) / price * 100, 2) if tp_price is not None else None

        if in_signal:
            rationale = f"Breakout confirmed: {breakout_pct:.1f}% above its {lookback_days}-day prior high ({volume_note})."
        elif breakout_pct >= breakout_threshold_pct:
            rationale = f"Price cleared the {lookback_days}-day high by {breakout_pct:.1f}% but {volume_note} - not confirmed yet."
        elif breakout_pct > 0:
            rationale = f"{breakout_pct:.1f}% above its {lookback_days}-day prior high - below the {breakout_threshold_pct:.1f}% breakout threshold."
        else:
            rationale = f"{abs(breakout_pct):.1f}% below its {lookback_days}-day prior high - no breakout forming."

        candidates.append(
            {
                "symbol": symbol,
                "unavailable": False,
                "direction": "buy",
                "cmp": price,
                "prior_high": round(prior_high, 2),
                "breakout_pct": breakout_pct,
                "stop_loss_price": sl_price,
                "target_price": tp_price,
                "upside_pct": upside_pct,
                "quantity": position_size(risk, price),
                "in_signal": in_signal,
                "proximity_pct": round(min(100.0, max(0.0, breakout_pct / breakout_threshold_pct * 100)), 1),
                "already_open": symbol in open_symbols,
                "rationale": rationale,
            }
        )

    candidates.sort(key=lambda c: c["breakout_pct"], reverse=True)
    return candidates[:top_n]


def enter_position(
    db: Session,
    agent_id: str | None,
    symbol: str,
    direction: Direction,
    quantity: int,
    ref_price: float,
    buy_stop_loss_pct: float | None,
    sell_stop_loss_pct: float | None,
    target_pct: float | None,
    is_manual: bool = False,
) -> Trade:
    """Entry + Protect (Section 4 steps 3-4), shared by agents and manual trades."""
    broker = get_broker_adapter()
    trade_id = str(uuid.uuid4())

    fill = broker.place_entry_order(
        client_order_id=f"{trade_id}:entry",
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        reference_price=ref_price,
    )

    sl_pct = buy_stop_loss_pct if direction == "buy" else sell_stop_loss_pct
    trade = Trade(
        trade_id=trade_id,
        agent_id=agent_id,
        stock_symbol=symbol,
        direction=direction,
        quantity=fill.quantity,
        buy_price=fill.price,
        purchase_date=fill.timestamp,
        status="open",
        broker_order_id=fill.order_id,
        is_manual=is_manual,
    )

    if sl_pct is not None:
        sl_price = stop_loss_price(direction, fill.price, sl_pct)
        sl_gtt = broker.place_gtt(
            client_order_id=f"{trade_id}:sl",
            symbol=symbol,
            direction=exit_direction(direction),
            trigger_price=sl_price,
            comparator="lte" if direction == "buy" else "gte",
            quantity=fill.quantity,
            kind="stop_loss",
        )
        trade.stop_loss_pct = sl_pct
        trade.stop_loss_price = sl_price
        trade.stop_loss_gtt_id = sl_gtt.gtt_id
    else:
        # Spec requires a stop-loss for agent trades (Section 1); manual
        # trades may opt out (Section 7.7 says stop-loss % is optional there).
        trade.stop_loss_pct = 0.0
        trade.stop_loss_price = 0.0

    if target_pct is not None:
        tp_price = target_price(direction, fill.price, target_pct)
        tp_gtt = broker.place_gtt(
            client_order_id=f"{trade_id}:tp",
            symbol=symbol,
            direction=exit_direction(direction),
            trigger_price=tp_price,
            comparator="gte" if direction == "buy" else "lte",
            quantity=fill.quantity,
            kind="target",
        )
        trade.target_pct = target_pct
        trade.target_price = tp_price
        trade.target_gtt_id = tp_gtt.gtt_id

    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def close_trade(db: Session, trade: Trade, sell_price: float, sell_time, exit_reason: str) -> None:
    """Exit + Log (Section 4 steps 6-7)."""
    broker = get_broker_adapter()

    other_gtt_id = (
        trade.target_gtt_id if exit_reason == "stop_loss" else trade.stop_loss_gtt_id
    )
    if other_gtt_id:
        broker.cancel_gtt(other_gtt_id)

    gross = (sell_price - trade.buy_price) * trade.quantity
    if trade.direction == "sell":
        gross = -gross  # short: profit when price falls

    charge_breakdown = compute_charges(trade.direction, trade.buy_price, sell_price, trade.quantity)
    tax = estimate_tax(gross, charge_breakdown.total)

    trade.sell_price = sell_price
    trade.sell_date = sell_time
    trade.exit_reason = exit_reason
    trade.gross_profit = round(gross, 2)
    trade.charges = charge_breakdown.total
    trade.tax = tax
    trade.net_profit = round(gross - charge_breakdown.total - tax, 2)
    trade.status = "closed"
    db.commit()


def modify_protection(
    db: Session,
    trade: Trade,
    new_stop_loss_price: float,
    new_target_price: float | None,
) -> Trade:
    """Re-place the GTT bracket on an OPEN position with edited stop-loss /
    target levels (Section 4 'Protect'). Kite exposes a GTT modify; here we
    cancel-and-replace, same net effect. Uses a fresh client_order_id each
    time because place_gtt is idempotent on that id - reusing the old one
    would just return the now-cancelled GTT instead of arming a new one.
    Recomputes the stored pct from buy_price so downstream displays (TSL,
    etc.) stay consistent."""
    if trade.status != "open":
        raise ValueError("Only open trades can be modified")

    broker = get_broker_adapter()
    exit_dir = exit_direction(trade.direction)

    # --- stop-loss (always present) ---
    if trade.stop_loss_gtt_id:
        broker.cancel_gtt(trade.stop_loss_gtt_id)
    sl_gtt = broker.place_gtt(
        client_order_id=f"{trade.trade_id}:sl:{uuid.uuid4().hex[:8]}",
        symbol=trade.stock_symbol,
        direction=exit_dir,
        trigger_price=round(new_stop_loss_price, 2),
        comparator="lte" if trade.direction == "buy" else "gte",
        quantity=trade.quantity,
        kind="stop_loss",
    )
    trade.stop_loss_price = round(new_stop_loss_price, 2)
    trade.stop_loss_gtt_id = sl_gtt.gtt_id
    if trade.buy_price:
        trade.stop_loss_pct = round(abs(new_stop_loss_price - trade.buy_price) / trade.buy_price * 100, 4)

    # --- target (optional - clearing it removes the take-profit leg) ---
    if trade.target_gtt_id:
        broker.cancel_gtt(trade.target_gtt_id)
        trade.target_gtt_id = None
    if new_target_price is not None:
        tp_gtt = broker.place_gtt(
            client_order_id=f"{trade.trade_id}:tp:{uuid.uuid4().hex[:8]}",
            symbol=trade.stock_symbol,
            direction=exit_dir,
            trigger_price=round(new_target_price, 2),
            comparator="gte" if trade.direction == "buy" else "lte",
            quantity=trade.quantity,
            kind="target",
        )
        trade.target_price = round(new_target_price, 2)
        trade.target_gtt_id = tp_gtt.gtt_id
        if trade.buy_price:
            trade.target_pct = round(abs(new_target_price - trade.buy_price) / trade.buy_price * 100, 4)
    else:
        trade.target_price = None
        trade.target_pct = None

    db.commit()
    db.refresh(trade)
    return trade


def estimate_trade_charges(trade: Trade, reference_price: float) -> dict:
    """Itemized charge + tax breakdown for the Net P&L breakup popup. For a
    closed trade, reference_price is the actual sell_price, so this
    reconstructs the same numbers already stored on trade.charges/trade.tax
    (those only store the totals, not the line items). For an open trade,
    reference_price is the latest quote - an estimate of what closing right
    now would cost, not yet finalized (finalization happens in close_trade)."""
    breakdown = compute_charges(trade.direction, trade.buy_price, reference_price, trade.quantity)
    gross = (reference_price - trade.buy_price) * trade.quantity
    if trade.direction == "sell":
        gross = -gross  # short: profit when price falls
    tax = estimate_tax(gross, breakdown.total)

    return {
        "brokerage": breakdown.brokerage,
        "stt": breakdown.stt,
        "exchange_txn": breakdown.exchange_txn,
        "sebi_charges": breakdown.sebi_charges,
        "stamp_duty": breakdown.stamp_duty,
        "gst": breakdown.gst,
        "total_charges": breakdown.total,
        "tax": tax,
        "gross_profit": round(gross, 2),
        "net_profit": round(gross - breakdown.total - tax, 2),
        "reference_price": round(reference_price, 2),
        "is_estimate": trade.status == "open",
    }


def run_agent_scan(db: Session, agent: Agent) -> None:
    """Scan -> Signal -> Entry -> Protect -> Log for one agent (Section 4)."""
    if not agent.active:
        return

    config = agent.config
    schedule = config.get("schedule", {})
    market_data_adapter = get_market_data_adapter()

    if schedule.get("market_hours_only", True) and not market_data_adapter.is_market_open():
        _log(db, agent.agent_id, None, "skipped", "outside market hours")
        db.commit()
        return

    universe_cfg = config["universe"]
    universe = universe_cfg["value"] if isinstance(universe_cfg["value"], list) else [universe_cfg["value"]]

    try:
        snapshot = market_data_adapter.get_snapshot(
            universe, lookback_days=config.get("strategy_params", {}).get("lookback_days", 20)
        )
    except MarketDataUnavailableError as exc:
        # Section 9 fail-safe: pause rather than act on stale/missing data.
        _log(db, agent.agent_id, None, "paused", f"market data unavailable: {exc}")
        db.commit()
        return

    risk = config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)
    open_count = _open_position_count(db, agent.agent_id)
    capital_used = _capital_committed_today(db, agent.agent_id)
    free_capital = get_capital_summary(db)["free_capital"]

    strategy = get_strategy(agent.strategy)
    signals = strategy.scan(universe, snapshot, config.get("strategy_params", {}))

    signalled_symbols = {s.symbol for s in signals}
    for symbol in universe:
        if symbol not in signalled_symbols:
            _log(db, agent.agent_id, symbol, "no_signal", "no entry criteria met")

    for signal in signals:
        if signal.symbol in open_symbols:
            _log(db, agent.agent_id, signal.symbol, "skipped", "already holding a position")
            continue
        if open_count >= risk["max_concurrent_positions"]:
            _log(db, agent.agent_id, signal.symbol, "skipped", "max_concurrent_positions reached")
            continue

        price = snapshot.prices[signal.symbol]
        qty = position_size(risk, price)
        if qty <= 0:
            _log(db, agent.agent_id, signal.symbol, "skipped", "position size rounds to 0 shares")
            continue

        trade_value = qty * price
        if capital_used + trade_value > risk["max_daily_capital"]:
            _log(db, agent.agent_id, signal.symbol, "skipped", "max_daily_capital reached")
            continue
        if trade_value > free_capital:
            # Section 9-style hard constraint: the account-wide capital pool
            # (shared across all agents + manual trades) takes priority over
            # this agent's own max_daily_capital allowance - an agent can't
            # spend money the account doesn't actually have.
            _log(db, agent.agent_id, signal.symbol, "skipped", "insufficient free capital")
            continue

        enter_position(
            db,
            agent_id=agent.agent_id,
            symbol=signal.symbol,
            direction=signal.direction,
            quantity=qty,
            ref_price=price,
            buy_stop_loss_pct=risk.get("buy_stop_loss_pct"),
            sell_stop_loss_pct=risk.get("sell_stop_loss_pct"),
            target_pct=risk.get("target_pct"),
        )
        _log(db, agent.agent_id, signal.symbol, "entered", signal.reason)
        db.commit()

        open_count += 1
        capital_used += trade_value
        free_capital -= trade_value
        open_symbols.add(signal.symbol)

    # Every "no_signal"/"skipped" AgentLog added above (Section 6.4
    # auditability) was only staged via db.add(), never committed, on any
    # path that didn't reach an actual entry - which is the common case
    # (most scans find nothing to buy). Without this, the entire scan
    # decision log for a no-op cycle silently vanished when the session
    # closed.
    db.commit()


def force_close(db: Session, trade: Trade, current_price: float, exit_reason: str) -> None:
    """Close a trade outside the normal GTT-trigger path: user-initiated
    early close (Section 7.7) or a time-based exit rule (Section 4)."""
    broker = get_broker_adapter()
    for gtt_id in (trade.stop_loss_gtt_id, trade.target_gtt_id):
        if gtt_id:
            broker.cancel_gtt(gtt_id)
    close_trade(db, trade, current_price, datetime.now(timezone.utc), exit_reason)


def close_trade_manually(db: Session, trade: Trade, current_price: float) -> None:
    """User-initiated early close (Section 7.7 'close a position early')."""
    force_close(db, trade, current_price, "manual")


def monitor_open_positions(db: Session) -> None:
    """Monitor -> Exit -> Log for every open trade, across all agents and
    manual trades (Section 4 step 5-7). Runs on its own scheduler cadence,
    independent of each agent's scan interval.

    Exit triggers are evaluated directly against each Trade's persisted
    stop_loss_price/target_price rather than the broker's in-memory GTT
    bookkeeping: the simulator's GttOrder objects live only in process
    memory and don't survive a restart, so a trade opened in a prior
    process lifetime would otherwise never be checked again no matter how
    far price moved past its levels.
    """
    market_data_adapter = get_market_data_adapter()

    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    if not open_trades:
        return

    symbols = list({t.stock_symbol for t in open_trades})
    try:
        snapshot = market_data_adapter.get_snapshot(symbols, lookback_days=1)
    except MarketDataUnavailableError:
        return  # fail-safe: skip this monitor cycle rather than act on nothing

    closed_trade_ids = set()
    for trade in open_trades:
        price = snapshot.prices.get(trade.stock_symbol)
        if price is None:
            continue

        exit_reason = None
        if trade.stop_loss_price:
            hit = (
                price <= trade.stop_loss_price
                if trade.direction == "buy"
                else price >= trade.stop_loss_price
            )
            if hit:
                exit_reason = "stop_loss"
        if exit_reason is None and trade.target_price:
            hit = (
                price >= trade.target_price
                if trade.direction == "buy"
                else price <= trade.target_price
            )
            if hit:
                exit_reason = "target"

        if exit_reason is not None:
            force_close(db, trade, price, exit_reason)
            _log(db, trade.agent_id, trade.stock_symbol, "exited", f"{exit_reason} triggered at {price}")
            db.commit()
            closed_trade_ids.add(trade.trade_id)

    # Time-based exit rule (Section 4 "Monitor... or a time-based exit rule
    # fires"), opt-in per agent via risk.max_hold_hours.
    now = datetime.now(timezone.utc)
    for trade in open_trades:
        if trade.trade_id in closed_trade_ids or trade.agent is None:
            continue
        max_hold_hours = trade.agent.config.get("risk", {}).get("max_hold_hours")
        if not max_hold_hours:
            continue
        purchase_date = trade.purchase_date
        if purchase_date.tzinfo is None:
            purchase_date = purchase_date.replace(tzinfo=timezone.utc)
        age_hours = (now - purchase_date).total_seconds() / 3600
        if age_hours >= max_hold_hours:
            price = snapshot.prices.get(trade.stock_symbol)
            if price is None:
                continue
            force_close(db, trade, price, "timeout")
            _log(db, trade.agent_id, trade.stock_symbol, "exited", f"timeout after {age_hours:.1f}h")
            db.commit()
