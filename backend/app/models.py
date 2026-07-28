import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


def _now():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class Agent(Base):
    """Section 6.2 - agents table."""

    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    strategy = Column(String, nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    # Trade now has two FKs to agents (agent_id, source_agent_id) - both
    # relationships must pin foreign_keys explicitly, otherwise SQLAlchemy
    # can't tell which column each join should use.
    trades = relationship("Trade", back_populates="agent", foreign_keys="Trade.agent_id")
    logs = relationship("AgentLog", back_populates="agent")


class Trade(Base):
    """Section 6.1 - trades table."""

    __tablename__ = "trades"

    trade_id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=True)
    # The Recommending agent whose signal led to this trade - only ever set
    # for llm_recommendation_execution trades (see _find_recommend_only_agents
    # in agent_runtime.py); null for manual trades and every other strategy,
    # and null for trades placed before this column existed. Lets the trade
    # log show which Recommending agent actually flagged a stock, not just
    # which agent placed the order.
    source_agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=True)
    stock_symbol = Column(String, nullable=False)
    direction = Column(Enum("buy", "sell", name="trade_direction"), nullable=False)
    quantity = Column(Integer, nullable=False)

    buy_price = Column(Float, nullable=False)
    sell_price = Column(Float, nullable=True)
    purchase_date = Column(DateTime(timezone=True), default=_now)
    sell_date = Column(DateTime(timezone=True), nullable=True)

    stop_loss_pct = Column(Float, nullable=False)
    stop_loss_price = Column(Float, nullable=False)
    target_pct = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)

    exit_reason = Column(
        Enum("stop_loss", "target", "manual", "timeout", name="exit_reason"),
        nullable=True,
    )

    gross_profit = Column(Float, nullable=True)
    charges = Column(Float, nullable=True, default=0.0)
    tax = Column(Float, nullable=True, default=0.0)
    net_profit = Column(Float, nullable=True)

    status = Column(Enum("open", "closed", "error", name="trade_status"), default="open")
    broker_order_id = Column(String, nullable=True)

    # Internal bookkeeping, not in the spec's column list: lets the monitor
    # loop map a triggered GTT fill (Section 4 "Monitor"/"Exit") back to the
    # trade it belongs to, and cancel the sibling GTT once one side fires.
    stop_loss_gtt_id = Column(String, nullable=True)
    target_gtt_id = Column(String, nullable=True)

    # Not in the spec's column list verbatim, but required to satisfy
    # Section 7.7's "tagged as manual rather than attributed to an agent" -
    # agent_id alone can't distinguish "manual" from "future untagged agent
    # trade", so an explicit flag avoids that ambiguity.
    is_manual = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    # The scanned_at of the LlmSignalCache row that produced the signal this
    # trade entered on - only ever set for llm_recommendation_execution
    # trades (see enter_position/_run_execution_agent_scan). Lets a later
    # scan tell "this is the same stale signal I already acted on" apart
    # from "the source agent has genuinely rescanned since" - without it,
    # a symbol whose position just closed re-enters on the very next tick
    # off the same hour-old cached signal (see the re-entry cooldown in
    # _run_execution_agent_scan).
    signal_scanned_at = Column(DateTime(timezone=True), nullable=True)

    agent = relationship("Agent", back_populates="trades", foreign_keys=[agent_id])


class LlmSignalCache(Base):
    """Throttles LLM API usage (Section 9-style guard-rail, MVP-hardcoded):
    the llm_recommendation strategy is only actually invoked once per
    rolling hour, within an 11:00-15:00 IST window - see
    agent_runtime.get_or_scan_llm_signals. Keyed by the Recommending
    agent's own agent_id so an llm_recommendation_execution agent
    mirroring that same prompt/universe (see _find_recommend_only_agents)
    reuses this same cache entry instead of doubling API spend."""

    __tablename__ = "llm_signal_cache"

    agent_id = Column(String, ForeignKey("agents.agent_id"), primary_key=True)
    # The resolved universe (symbol list) from the same scan that produced
    # signals_json - cached alongside it so a cache hit skips the screener
    # entirely (the expensive, rate-limit-prone part - see get_tiered_trending_symbols)
    # rather than only skipping the LLM call. Nullable for rows written
    # before this column existed (see app.db.init_db's inline migration);
    # get_or_scan_llm_signals treats a null value as "not usable, re-scan."
    universe_json = Column(Text, nullable=True)
    signals_json = Column(Text, nullable=False)
    # Nullable so a row can exist purely to record a failed first-ever
    # attempt (last_error set below) before any scan has ever succeeded -
    # cache_usable (get_or_scan_llm_signals) gates on universe_json, not
    # this column, so that path never touches scanned_at while it's null.
    scanned_at = Column(DateTime(timezone=True), nullable=True)
    # Recorded on every real scan attempt (not cache-served reads), success
    # or failure - lets the UI distinguish "quiet, no signals today" from
    # "the LLM call has actually been failing" (see LlmCallFailedError),
    # which look identical from signals_json alone. last_error is cleared
    # back to null on the next successful attempt.
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)


class AgentLog(Base):
    """Section 6.4 - agent_logs table (scan decisions, including non-trades)."""

    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=_now)
    # Nullable: exit events for manual trades (Section 7.7) also flow
    # through monitor_open_positions() and have no owning agent.
    agent_id = Column(String, ForeignKey("agents.agent_id"), nullable=True)
    symbol = Column(String, nullable=True)
    decision = Column(String, nullable=False)  # e.g. "signal", "no_signal", "error"
    reason = Column(Text, nullable=True)

    agent = relationship("Agent", back_populates="logs")
