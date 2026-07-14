"""
External-trigger endpoint for sleep-prone free-tier hosts (Section 8/9).

APScheduler's in-process timer (scheduler.py) only fires while the process
happens to be awake - on Render's free tier, a periodic keep-alive ping
(UptimeRobot, cron-job.org) is needed just to prevent the instance from
sleeping, and even then a scan is only guaranteed if the internal timer
lines up with an awake window.

This endpoint makes the ping itself the trigger: point the external pinger
at POST /cron/tick instead of GET /health, and every ping directly runs one
real scan-and-monitor cycle (live yfinance fetch, GTT checks, trade entry/
exit) synchronously in that request - no dependency on the internal timer
surviving a sleep gap. The in-process scheduler keeps running too (harmless
if it fires around the same time - run_agent_scan/monitor_open_positions
are idempotent per cycle), this is a resilience addition, not a replacement.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent_runtime import monitor_open_positions, run_agent_scan
from app.db import get_db
from app.models import Agent

router = APIRouter(prefix="/cron", tags=["cron"])


@router.post("/tick")
def cron_tick(db: Session = Depends(get_db)):
    agent_ids_scanned = []
    for agent in db.query(Agent).filter(Agent.active.is_(True)).all():
        run_agent_scan(db, agent)
        agent_ids_scanned.append(agent.agent_id)

    monitor_open_positions(db)

    return {"agents_scanned": agent_ids_scanned, "monitor_ran": True}
