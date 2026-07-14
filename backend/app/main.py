from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_auth
from app.config import settings
from app.db import init_db
from app.routers import agents, cron, dashboard, trades
from app.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield


app = FastAPI(title="Agentic Stop-Loss Trading System", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /health is deliberately outside the auth gate so uptime checks/load
# balancers can probe it without credentials. /cron/tick stays behind auth
# even though it's also meant to be hit by an external pinger - unlike
# /health it triggers real trading activity, so it needs the same
# credentials as everything else (most uptime-ping services, including
# UptimeRobot's free tier, support Basic Auth on the monitored URL).
app.include_router(agents.router, dependencies=[Depends(require_auth)])
app.include_router(trades.router, dependencies=[Depends(require_auth)])
app.include_router(dashboard.router, dependencies=[Depends(require_auth)])
app.include_router(cron.router, dependencies=[Depends(require_auth)])


@app.get("/health")
def health():
    return {"status": "ok"}
