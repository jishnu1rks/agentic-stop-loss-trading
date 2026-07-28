from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent_runtime import (
    build_llm_execution_recommendations,
    build_llm_recommendations,
    build_momentum_recommendations,
    build_watchlist_recommendations,
)
from app.adapters.market_data.yfinance_adapter import MarketDataUnavailableError
from app.db import get_db
from app.models import Agent, AgentLog, LlmSignalCache
from app.scheduler import schedule_agent, unschedule_agent
from app.schemas import AgentConfigIn, AgentOut, LlmStatusOut

router = APIRouter(prefix="/agents", tags=["agents"])


def _config_dict(payload: AgentConfigIn) -> dict:
    return {
        "agent_id": payload.agent_id,
        "name": payload.name,
        "active": payload.active,
        "universe": payload.universe.model_dump(),
        "strategy": payload.strategy,
        "strategy_params": payload.strategy_params,
        "risk": payload.risk.model_dump() if payload.risk is not None else None,
        "schedule": payload.schedule.model_dump(),
    }


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite has no native tz-aware datetime type, so a DateTime(timezone=True)
    column round-trips as a naive datetime even though it only ever holds
    UTC values (see get_or_scan_llm_signals's identical fixup for
    scanned_at) - left naive, FastAPI serializes it with no 'Z'/offset,
    and a non-UTC browser then parses that string as ITS OWN local time,
    silently shifting "last scan" by the browser's UTC offset."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def _attach_llm_status(agents: list[Agent], db: Session) -> list[Agent]:
    """Populates AgentOut.llm_status for every strategy=='llm_recommendation'
    agent from its LlmSignalCache row (get_or_scan_llm_signals is what
    writes last_attempted_at/last_error there) - a plain attribute set on
    the ORM instance, read straight back off by Pydantic's from_attributes
    when serializing as AgentOut."""
    llm_agent_ids = [a.agent_id for a in agents if a.strategy == "llm_recommendation"]
    caches = (
        {c.agent_id: c for c in db.query(LlmSignalCache).filter(LlmSignalCache.agent_id.in_(llm_agent_ids)).all()}
        if llm_agent_ids
        else {}
    )
    for agent in agents:
        cache = caches.get(agent.agent_id)
        agent.llm_status = (
            LlmStatusOut(
                last_scanned_at=_as_utc(cache.scanned_at),
                last_attempted_at=_as_utc(cache.last_attempted_at),
                last_error=cache.last_error,
            )
            if cache is not None
            else None
        )
    return agents


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return _attach_llm_status(db.query(Agent).all(), db)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")
    _attach_llm_status([agent], db)
    return agent


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(payload: AgentConfigIn, db: Session = Depends(get_db)):
    if db.query(Agent).filter(Agent.agent_id == payload.agent_id).first():
        raise HTTPException(409, f"Agent '{payload.agent_id}' already exists")

    agent = Agent(
        agent_id=payload.agent_id,
        name=payload.name,
        strategy=payload.strategy,
        config=_config_dict(payload),
        active=payload.active,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    schedule_agent(agent)
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, payload: AgentConfigIn, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")
    if payload.agent_id != agent_id:
        raise HTTPException(400, "agent_id in body must match URL")

    agent.name = payload.name
    agent.strategy = payload.strategy
    agent.config = _config_dict(payload)
    agent.active = payload.active
    db.commit()
    db.refresh(agent)
    schedule_agent(agent)
    return agent


@router.post("/{agent_id}/activate", response_model=AgentOut)
def set_active(agent_id: str, active: bool, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")
    agent.active = active
    db.commit()
    db.refresh(agent)
    schedule_agent(agent)
    return agent


@router.get("/{agent_id}/activity")
def agent_activity(agent_id: str, limit: int = 30, db: Session = Depends(get_db)):
    """Section 6.4: surface what a watchlist agent is actually watching
    (universe + strategy_params) and its most recent scan decisions, so
    "why hasn't this agent traded" is answerable from the dashboard
    without a direct DB query."""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")

    logs = (
        db.query(AgentLog)
        .filter(AgentLog.agent_id == agent_id)
        .order_by(AgentLog.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "active": agent.active,
        "strategy": agent.strategy,
        "universe": agent.config.get("universe"),
        "strategy_params": agent.config.get("strategy_params"),
        "schedule": agent.config.get("schedule"),
        "recent_logs": [
            {
                "timestamp": log.timestamp,
                "symbol": log.symbol,
                "decision": log.decision,
                "reason": log.reason,
            }
            for log in logs
        ],
    }


@router.get("/{agent_id}/recommendations")
def agent_recommendations(
    agent_id: str,
    top_n: int = 10,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Live trade-idea cards for an agent's universe - current price,
    computed target/stop-loss, position size, and a plain rationale. Not a
    persisted signal, just a read of the agent's own criteria against
    right-now prices. Dispatches by strategy: watchlist_trigger checks a
    fixed set of hand-configured bands; momentum_breakout scans and ranks
    the agent's whole universe (Section 5.2/5.3).

    force=True is a manual, human-initiated override for the two LLM
    strategies only, bypassing get_or_scan_llm_signals' 1-hour/11:00-15:00
    guard-rail for testing (see the dashboard's "Force rescan" button) -
    ignored for the other strategies, which were never throttled."""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")

    try:
        if agent.strategy == "watchlist_trigger":
            return build_watchlist_recommendations(db, agent)
        if agent.strategy == "momentum_breakout":
            return build_momentum_recommendations(db, agent, top_n=top_n)
        if agent.strategy == "llm_recommendation":
            return build_llm_recommendations(db, agent, force=force)
        if agent.strategy == "llm_recommendation_execution":
            return build_llm_execution_recommendations(db, agent, force=force)
    except MarketDataUnavailableError as exc:
        raise HTTPException(503, f"Market data unavailable: {exc}") from exc

    raise HTTPException(400, f"Recommendations view is not implemented for strategy '{agent.strategy}'")


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")
    unschedule_agent(agent_id)
    db.delete(agent)
    db.commit()
