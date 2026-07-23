"""
Core trading flow (Section 4): Scan -> Signal -> Entry -> Protect -> Monitor
-> Exit -> Log -> Report. Shared by every strategy module (Section 5.3) and
by manual trades (Section 7.7), which go through the same Broker Adapter so
simulation vs. live behaviour stays consistent.
"""
import json
import math
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.adapters.broker import get_broker_adapter
from app.adapters.broker.base import Direction
from app.adapters.market_data import get_market_data_adapter
from app.adapters.market_data.base import MarketDataSnapshot
from app.adapters.market_data.yfinance_adapter import IST, MarketDataUnavailableError
from app.charges import compute_charges
from app.config import settings
from app.fundamentals import classify_cap_size, is_recommendable
from app.models import Agent, AgentLog, LlmSignalCache, Trade
from app.strategies import get_strategy
from app.strategies.base import Signal
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


def position_size(budget: float, price: float) -> int:
    """No fixed per-trade amount to configure - a signal spends whatever
    capital is actually available for it, capped by the caller-supplied
    budget (typically min(account-wide free capital, this agent's
    remaining max_daily_capital allowance) - see trade_budget)."""
    if price <= 0:
        return 0
    return max(int(budget // price), 0)


# Hard per-trade ceiling (Section 9-style guard-rail): no single trade may
# commit more than this fraction of an agent's max_daily_capital, even if
# free capital and the day's remaining allowance would allow more - keeps
# one signal from swallowing a whole day's budget in a single trade.
MAX_TRADE_PCT_OF_DAILY_CAPITAL = 0.25


def trade_budget(risk: dict, free_capital: float, capital_used_today: float) -> float:
    remaining_daily_allowance = max(risk["max_daily_capital"] - capital_used_today, 0)
    max_per_trade = risk["max_daily_capital"] * MAX_TRADE_PCT_OF_DAILY_CAPITAL
    return min(free_capital, remaining_daily_allowance, max_per_trade)


# llm_recommendation agents (Section 5.2's Recommending agent) carry no risk
# config of their own - they never size or place a trade. The target/stop-loss/
# qty shown on their idea cards are illustrative only (same guard-rail
# percentages this system uses elsewhere), so a viewer has a concrete sense of
# scale; a human still decides real sizing and risk before acting on an idea.
RECOMMENDATION_STOP_LOSS_PCT = 1.5
RECOMMENDATION_TARGET_PCT = 3.0
RECOMMENDATION_BUDGET_PCT_OF_FREE_CAPITAL = 0.25


def _open_position_count(db: Session, agent_id: str) -> int:
    return (
        db.query(func.count(Trade.trade_id))
        .filter(Trade.agent_id == agent_id, Trade.status == "open")
        .scalar()
        or 0
    )


def _capital_committed_today(db: Session, agent_id: str) -> float:
    """Only counts trades entered today that are still open - a closed
    trade's capital is back in the free-capital pool, so it shouldn't also
    keep counting against today's max_daily_capital allowance. (A position
    opened on an earlier day and still open today isn't included either -
    it was already charged against the day it was actually entered.)"""
    today = datetime.now(timezone.utc).date()
    rows = (
        db.query(Trade.buy_price, Trade.quantity)
        .filter(
            Trade.agent_id == agent_id,
            func.date(Trade.purchase_date) == str(today),
            Trade.status == "open",
        )
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


def resolve_universe(config: dict, market_data_adapter) -> list[str]:
    """Resolve an agent's configured universe into a concrete symbol list.
    "watchlist"/"index" are just a stored list; "screener" (Section 5.1)
    instead defers to the market data adapter's live top-N discovery, so the
    universe is today's most-active/biggest-movers rather than a
    hand-maintained list. May raise MarketDataUnavailableError - callers
    already treat that as a fail-safe pause for get_snapshot, so it's raised
    here rather than swallowed."""
    universe_cfg = config["universe"]
    if universe_cfg.get("type") == "screener":
        screener = universe_cfg.get("screener") or {}
        if config.get("strategy") == "llm_recommendation":
            # MVP: the Recommending agent always gets a fixed 5 large/5
            # mid/5 small-cap spread rather than one flat top-N-by-volume
            # list, which otherwise skews almost entirely large-cap.
            trending = market_data_adapter.get_tiered_trending_symbols(
                large_count=5, mid_count=5, small_count=5,
                sort_by=screener.get("sort_by", "dayvolume"),
            )
        else:
            trending = market_data_adapter.get_trending_symbols(
                sort_by=screener.get("sort_by", "dayvolume"),
                limit=screener.get("limit", 15),
                min_market_cap=screener.get("min_market_cap", 5_000_000_000),
            )
        return filter_recommendable(trending, market_data_adapter)
    value = universe_cfg["value"]
    return value if isinstance(value, list) else [value]


def filter_recommendable(symbols: list[str], market_data_adapter) -> list[str]:
    """Standard fundamentals bar for a "screener" universe (Section 5.1) -
    a trending symbol only enters the pool an agent actually scans if it
    clears app.fundamentals.is_recommendable's financial-health/valuation
    screen. A symbol whose fundamentals can't be fetched at all is kept
    rather than dropped, since a data-source hiccup on one name shouldn't
    silently shrink the universe for every agent using it."""
    kept = []
    for symbol in symbols:
        fundamentals = market_data_adapter.get_fundamentals(symbol)
        if fundamentals is None:
            kept.append(symbol)
            continue
        recommendable, _, _ = is_recommendable(fundamentals)
        if recommendable:
            kept.append(symbol)
    return kept


# MVP hard limit (Section 9-style guard-rail) on LLM API usage: the
# free-tier quota this system currently runs on is exhausted almost
# instantly if every scheduler tick and every dashboard load each fire
# their own live call - see get_or_scan_llm_signals. Not yet
# user-configurable; surfaced as a note in the agent settings UI instead.
LLM_SCAN_WINDOW_START = time(11, 0)
LLM_SCAN_WINDOW_END = time(15, 0)
LLM_SCAN_MIN_INTERVAL = timedelta(hours=1)


def _serialize_signals(signals: list[Signal]) -> str:
    return json.dumps(
        [
            {"symbol": s.symbol, "direction": s.direction, "confidence": s.confidence, "reason": s.reason}
            for s in signals
        ]
    )


def _deserialize_signals(signals_json: str) -> list[Signal]:
    return [Signal(**item) for item in json.loads(signals_json)]


def get_or_scan_llm_signals(
    db: Session,
    cache_key: str,
    config: dict,
    market_data_adapter,
    force: bool = False,
) -> tuple[list[str], MarketDataSnapshot, list[Signal]]:
    """Throttled front door for the llm_recommendation strategy's full
    Scan step (universe resolution + market snapshot + LLM call): at most
    one real LLM call per rolling hour, and only within an 11:00-15:00 IST
    window - every other call (scheduler tick or on-demand recommendations
    fetch) reuses the cached universe/signals instead of re-running any of
    it. Outside the window, falls back to the last cached universe/result
    (or empty if none exists yet) rather than blocking entirely, so the
    dashboard doesn't go blank outside trading hours.

    Universe resolution is cached alongside the signals - not just the LLM
    call - because get_tiered_trending_symbols hits Yahoo's unofficial
    screener endpoint 3x per scan (one per cap tier), which is the part
    that actually gets rate-limited in practice; re-running it on every
    dashboard load defeated the point of throttling the LLM call. The
    price snapshot is still fetched fresh every call (a separate,
    less rate-limit-prone yfinance endpoint) so displayed prices stay live
    even when the universe/signals are served from cache.

    cache_key is always the Recommending agent's own agent_id, even when
    called on behalf of an llm_recommendation_execution agent mirroring
    its prompt/universe (see _find_recommend_only_agent) - the two share
    one cache entry rather than each spending their own quota.

    force=True bypasses both the 1-hour interval and the 11:00-15:00
    window entirely - a manual, human-initiated override for testing (see
    the dashboard's "Force rescan" button), never set by the scheduler or
    a normal recommendations fetch, so it can't turn into an automated way
    around the MVP quota guard-rail."""
    strategy_params = config.get("strategy_params", {})
    lookback_days = strategy_params.get("lookback_days", 20)
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    cached = db.query(LlmSignalCache).filter_by(agent_id=cache_key).first()
    cache_usable = bool(cached and cached.universe_json)

    def _from_cache() -> tuple[list[str], MarketDataSnapshot, list[Signal]]:
        universe = json.loads(cached.universe_json)
        snapshot = market_data_adapter.get_snapshot(universe, lookback_days=lookback_days)
        return universe, snapshot, _deserialize_signals(cached.signals_json)

    if not force and cache_usable:
        scanned_at = cached.scanned_at
        if scanned_at.tzinfo is None:
            scanned_at = scanned_at.replace(tzinfo=timezone.utc)
        if now_utc - scanned_at < LLM_SCAN_MIN_INTERVAL:
            return _from_cache()

    if not force and not (LLM_SCAN_WINDOW_START <= now_ist.time() <= LLM_SCAN_WINDOW_END):
        if cache_usable:
            return _from_cache()
        return [], MarketDataSnapshot(prices={}, history={}, volumes={}), []

    universe = resolve_universe(config, market_data_adapter)
    snapshot = market_data_adapter.get_snapshot(universe, lookback_days=lookback_days)
    signals = get_strategy("llm_recommendation").scan(universe, snapshot, strategy_params)

    if cached:
        cached.universe_json = json.dumps(universe)
        cached.signals_json = _serialize_signals(signals)
        cached.scanned_at = now_utc
    else:
        db.add(
            LlmSignalCache(
                agent_id=cache_key,
                universe_json=json.dumps(universe),
                signals_json=_serialize_signals(signals),
                scanned_at=now_utc,
            )
        )
    db.commit()
    return universe, snapshot, signals


def _cap_size_for(symbol: str, market_data_adapter) -> str | None:
    fundamentals = market_data_adapter.get_fundamentals(symbol)
    if fundamentals is None:
        return None
    return classify_cap_size(fundamentals.get("market_cap"))


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
    budget = trade_budget(risk, get_capital_summary(db)["free_capital"], _capital_committed_today(db, agent.agent_id))

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
                "quantity": position_size(budget, cmp),
                "in_band": in_band,
                "proximity_pct": _band_proximity_pct(cmp, low, high),
                "already_open": symbol in open_symbols,
                "rationale": rationale,
                "cap_size": _cap_size_for(symbol, market_data_adapter),
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
    universe = resolve_universe(config, market_data_adapter)
    strategy_params = config.get("strategy_params", {})
    lookback_days = strategy_params.get("lookback_days", 20)
    breakout_threshold_pct = strategy_params.get("breakout_threshold_pct", 2.0)
    volume_multiplier = strategy_params.get("volume_confirmation_multiplier", 1.0)
    risk = config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)
    budget = trade_budget(risk, get_capital_summary(db)["free_capital"], _capital_committed_today(db, agent.agent_id))

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
                "quantity": position_size(budget, price),
                "in_signal": in_signal,
                "proximity_pct": round(min(100.0, max(0.0, breakout_pct / breakout_threshold_pct * 100)), 1),
                "already_open": symbol in open_symbols,
                "rationale": rationale,
            }
        )

    candidates.sort(key=lambda c: c["breakout_pct"], reverse=True)
    top = candidates[:top_n]
    # Fundamentals lookups are per-symbol network calls, so only pay for them
    # on the candidates actually being returned, not the whole scanned universe.
    for candidate in top:
        candidate["cap_size"] = _cap_size_for(candidate["symbol"], market_data_adapter)
    return top


def build_llm_recommendations(db: Session, agent: Agent, force: bool = False) -> list[dict]:
    """Live trade-idea cards for an llm_recommendation agent (Section 5.2's
    Recommending agent): runs the same LLM call run_agent_scan would make
    against right-now prices, and turns any returned signals into cards.
    This strategy never sizes or places a trade itself (that's the Execution
    agent's job) and carries no risk config, so target/stop-loss/qty here are
    illustrative (RECOMMENDATION_* defaults), not agent-configured - a human
    decides real sizing and risk if they act on one."""
    market_data_adapter = get_market_data_adapter()
    config = agent.config
    open_symbols = _open_symbols(db, agent.agent_id)
    free_capital = get_capital_summary(db)["free_capital"]
    budget = free_capital * RECOMMENDATION_BUDGET_PCT_OF_FREE_CAPITAL

    _universe, snapshot, signals = get_or_scan_llm_signals(db, agent.agent_id, config, market_data_adapter, force=force)

    recommendations = []
    for signal in signals:
        price = snapshot.prices.get(signal.symbol)
        if price is None:
            continue

        history = snapshot.history.get(signal.symbol)
        prior_high = round(max(history[:-1]), 2) if history and len(history) >= 2 else None

        sl_price = stop_loss_price(signal.direction, price, RECOMMENDATION_STOP_LOSS_PCT)
        tp_price = target_price(signal.direction, price, RECOMMENDATION_TARGET_PCT)
        upside_pct = round(
            (tp_price - price) / price * 100 if signal.direction == "buy" else (price - tp_price) / price * 100, 2
        )

        recommendations.append(
            {
                "symbol": signal.symbol,
                "unavailable": False,
                "direction": signal.direction,
                "cmp": price,
                "prior_high": prior_high,
                "stop_loss_price": sl_price,
                "target_price": tp_price,
                "upside_pct": upside_pct,
                "quantity": position_size(budget, price),
                "in_signal": True,
                "proximity_pct": round(min(100.0, max(0.0, signal.confidence * 100)), 1),
                "already_open": signal.symbol in open_symbols,
                "rationale": signal.reason,
                "cap_size": _cap_size_for(signal.symbol, market_data_adapter),
            }
        )
    return recommendations


def _find_recommend_only_agent(db: Session) -> Agent | None:
    """The Recommending agent (Section 5.2) that llm_recommendation_execution
    agents mirror the prompt/universe of - identified as the active
    llm_recommendation-strategy agent with no risk config, i.e. the one that
    only ever produces ideas, never trades itself."""
    candidates = db.query(Agent).filter(Agent.strategy == "llm_recommendation", Agent.active == True).all()  # noqa: E712
    for candidate in candidates:
        if candidate.config.get("risk") is None:
            return candidate
    return None


def _filter_execution_signals(signals: list[Signal], strategy_params: dict) -> list[Signal]:
    """Execution-agent-only guard-rails on top of the mirrored Recommending
    agent's signals (Section 5.2's Execution agent). Previously nothing on
    the execution agent's own strategy_params was ever read - every
    mirrored signal entered unconditionally, subject only to
    capital/max_concurrent_positions limits. min_confidence_pct (0-100,
    matching this system's existing %-based risk fields) and directions
    default to "no filtering"/"both" so agents saved before this existed
    keep today's behavior unless explicitly changed."""
    min_confidence_pct = strategy_params.get("min_confidence_pct") or 0
    directions = strategy_params.get("directions", "both")
    allowed = {"buy", "sell"} if directions == "both" else {directions}
    return [s for s in signals if s.confidence * 100 >= min_confidence_pct and s.direction in allowed]


def build_llm_execution_recommendations(db: Session, agent: Agent, force: bool = False) -> list[dict]:
    """Live trade-idea cards for an llm_recommendation_execution agent (an
    Execution agent that trades off the Recommending agent's own LLM
    signals instead of fixed bands/breakouts): mirrors the Recommending
    agent's prompt/universe exactly (see _find_recommend_only_agent), but
    prices target/stop-loss/qty from THIS agent's own risk config, since
    it's the one that actually enters trades on these signals (see
    run_agent_scan)."""
    market_data_adapter = get_market_data_adapter()
    source_agent = _find_recommend_only_agent(db)
    if source_agent is None:
        return []

    source_config = source_agent.config
    risk = agent.config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)
    budget = trade_budget(risk, get_capital_summary(db)["free_capital"], _capital_committed_today(db, agent.agent_id))

    _universe, snapshot, signals = get_or_scan_llm_signals(
        db, source_agent.agent_id, source_config, market_data_adapter, force=force
    )
    signals = _filter_execution_signals(signals, agent.config.get("strategy_params", {}))

    recommendations = []
    for signal in signals:
        price = snapshot.prices.get(signal.symbol)
        if price is None:
            continue

        history = snapshot.history.get(signal.symbol)
        prior_high = round(max(history[:-1]), 2) if history and len(history) >= 2 else None
        breakout_pct = round((price - prior_high) / prior_high * 100, 2) if prior_high else None

        sl_pct = risk["buy_stop_loss_pct"] if signal.direction == "buy" else risk["sell_stop_loss_pct"]
        sl_price = stop_loss_price(signal.direction, price, sl_pct)
        tp_price = target_price(signal.direction, price, risk["target_pct"]) if risk.get("target_pct") else None
        upside_pct = None
        if tp_price is not None:
            upside_pct = round(
                (tp_price - price) / price * 100 if signal.direction == "buy" else (price - tp_price) / price * 100, 2
            )

        recommendations.append(
            {
                "symbol": signal.symbol,
                "unavailable": False,
                "direction": signal.direction,
                "cmp": price,
                "prior_high": prior_high,
                "breakout_pct": breakout_pct,
                "stop_loss_price": sl_price,
                "target_price": tp_price,
                "upside_pct": upside_pct,
                "quantity": position_size(budget, price),
                "in_signal": True,
                "proximity_pct": round(min(100.0, max(0.0, signal.confidence * 100)), 1),
                "already_open": signal.symbol in open_symbols,
                "rationale": signal.reason,
                "cap_size": _cap_size_for(signal.symbol, market_data_adapter),
                "source_agent_name": source_agent.name,
            }
        )
    return recommendations


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
    source_agent_id: str | None = None,
) -> Trade:
    """Entry + Protect (Section 4 steps 3-4), shared by agents and manual
    trades. source_agent_id is only ever passed for llm_recommendation_execution
    trades - the Recommending agent whose signal this mirrors (see
    run_agent_scan) - so the trade log can show which Recommending agent
    actually flagged the stock, not just which agent placed the order."""
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
        source_agent_id=source_agent_id,
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
    """Scan -> Signal -> Entry -> Protect -> Log for one agent (Section 4).
    Recommend-only strategies (llm_recommendation - Section 5.2's
    Recommending agent) stop after Signal: they carry no risk config to size
    or protect a position with, by design - placing trades is the Execution
    agent's job, not theirs. An llm_recommendation_execution agent (the
    Execution agent) does that job: it mirrors the Recommending agent's own
    universe/prompt exactly rather than scanning its own (see
    _find_recommend_only_agent), then sizes/enters trades on those same
    signals using its own risk config below, same as any other strategy."""
    if not agent.active:
        return

    config = agent.config
    schedule = config.get("schedule", {})
    market_data_adapter = get_market_data_adapter()

    if schedule.get("market_hours_only", True) and not market_data_adapter.is_market_open():
        _log(db, agent.agent_id, None, "skipped", "outside market hours")
        db.commit()
        return

    scan_config = config
    llm_cache_key = agent.agent_id
    if agent.strategy == "llm_recommendation_execution":
        source_agent = _find_recommend_only_agent(db)
        if source_agent is None:
            _log(db, agent.agent_id, None, "paused", "no Recommending agent configured to mirror")
            db.commit()
            return
        scan_config = source_agent.config
        llm_cache_key = source_agent.agent_id

    try:
        if agent.strategy in ("llm_recommendation", "llm_recommendation_execution"):
            # Throttled: at most 1 real universe-resolve + LLM call per
            # rolling hour, only 11:00-15:00 IST - see get_or_scan_llm_signals.
            universe, snapshot, signals = get_or_scan_llm_signals(db, llm_cache_key, scan_config, market_data_adapter)
        else:
            universe = resolve_universe(scan_config, market_data_adapter)
            snapshot = market_data_adapter.get_snapshot(
                universe, lookback_days=scan_config.get("strategy_params", {}).get("lookback_days", 20)
            )
            strategy = get_strategy(agent.strategy)
            signals = strategy.scan(universe, snapshot, scan_config.get("strategy_params", {}))
    except MarketDataUnavailableError as exc:
        # Section 9 fail-safe: pause rather than act on stale/missing data.
        _log(db, agent.agent_id, None, "paused", f"market data unavailable: {exc}")
        db.commit()
        return

    if agent.strategy == "llm_recommendation_execution":
        signals = _filter_execution_signals(signals, config.get("strategy_params", {}))

    signalled_symbols = {s.symbol for s in signals}
    for symbol in universe:
        if symbol not in signalled_symbols:
            _log(db, agent.agent_id, symbol, "no_signal", "no entry criteria met")

    if agent.strategy == "llm_recommendation":
        # Recommend-only: log what the model flagged for visibility, but
        # never size or enter a position - see build_llm_recommendations for
        # the live, on-demand version of this same scan that the
        # Recommendations view actually reads from.
        for signal in signals:
            _log(db, agent.agent_id, signal.symbol, "recommended", signal.reason)
        db.commit()
        return

    risk = config["risk"]
    open_symbols = _open_symbols(db, agent.agent_id)
    open_count = _open_position_count(db, agent.agent_id)
    capital_used = _capital_committed_today(db, agent.agent_id)
    free_capital = get_capital_summary(db)["free_capital"]

    for signal in signals:
        if signal.symbol in open_symbols:
            _log(db, agent.agent_id, signal.symbol, "skipped", "already holding a position")
            continue
        if open_count >= risk["max_concurrent_positions"]:
            _log(db, agent.agent_id, signal.symbol, "skipped", "max_concurrent_positions reached")
            continue

        price = snapshot.prices[signal.symbol]
        # No fixed per-trade amount to configure - each signal spends
        # whatever's left of this agent's max_daily_capital allowance,
        # capped by the account-wide free capital pool shared across every
        # agent and manual trade (Section 9-style hard constraint: an agent
        # can't spend money the account doesn't actually have).
        budget = trade_budget(risk, free_capital, capital_used)
        qty = position_size(budget, price)
        if qty <= 0:
            _log(db, agent.agent_id, signal.symbol, "skipped", "insufficient capital for even 1 share")
            continue

        trade_value = qty * price

        enter_position(
            db,
            agent_id=agent.agent_id,
            source_agent_id=llm_cache_key if agent.strategy == "llm_recommendation_execution" else None,
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
