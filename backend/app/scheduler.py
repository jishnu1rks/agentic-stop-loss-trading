"""
Scheduling (Section 8: APScheduler for periodic agent scans). Each active
agent gets its own interval job (Section 5.1 "runs on its own
schedule/trigger"); a single shared job monitors all open positions for
GTT triggers, independent of individual agent cadences.

Section 9 rate-limit note: jobs run against the simulator now, but the same
executor is capped (max_workers) so a future Kite adapter isn't hit by more
concurrent scans than its rate limit allows.
"""
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from app.agent_runtime import monitor_open_positions, run_agent_scan
from app.config import settings
from app.db import SessionLocal
from app.models import Agent

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(settings.scheduler_max_concurrent_scans)}
)


def _run_agent_scan_job(agent_id: str) -> None:
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if agent is not None:
            run_agent_scan(db, agent)
    finally:
        db.close()


def _monitor_job() -> None:
    db = SessionLocal()
    try:
        monitor_open_positions(db)
    finally:
        db.close()


def _job_id(agent_id: str) -> str:
    return f"agent-scan:{agent_id}"


def schedule_agent(agent: Agent) -> None:
    unschedule_agent(agent.agent_id)
    if not agent.active:
        return
    interval_minutes = agent.config.get("schedule", {}).get("interval_minutes", 5)
    scheduler.add_job(
        _run_agent_scan_job,
        "interval",
        minutes=interval_minutes,
        args=[agent.agent_id],
        id=_job_id(agent.agent_id),
        replace_existing=True,
        # APScheduler's default misfire_grace_time is 1 second - a scan that
        # takes longer than that to become due (e.g. a 50-symbol NIFTY50
        # batch fetch queued behind another job on the shared executor)
        # gets silently skipped entirely, not just delayed. coalesce=True
        # collapses any backlog into a single run instead of firing once
        # per missed interval.
        misfire_grace_time=None,
        coalesce=True,
    )


def unschedule_agent(agent_id: str) -> None:
    job_id = _job_id(agent_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def start_scheduler() -> None:
    db = SessionLocal()
    try:
        for agent in db.query(Agent).filter(Agent.active.is_(True)).all():
            schedule_agent(agent)
    finally:
        db.close()

    if not scheduler.get_job("monitor-positions"):
        scheduler.add_job(
            _monitor_job,
            "interval",
            minutes=1,
            id="monitor-positions",
            replace_existing=True,
            misfire_grace_time=None,
            coalesce=True,
        )

    if not scheduler.running:
        scheduler.start()
