from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agent_runtime import get_capital_summary
from app.db import get_db
from app.models import Agent, Trade

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _trades_df(db: Session, include_manual: bool = True) -> pd.DataFrame:
    query = db.query(Trade)
    if not include_manual:
        query = query.filter(Trade.is_manual.is_(False))
    rows = query.all()
    if not rows:
        return pd.DataFrame(
            columns=[
                "trade_id", "agent_id", "stock_symbol", "direction", "quantity",
                "buy_price", "sell_price", "purchase_date", "sell_date",
                "exit_reason", "gross_profit", "charges", "tax", "net_profit",
                "status", "is_manual",
            ]
        )
    return pd.DataFrame(
        [
            {
                "trade_id": t.trade_id,
                "agent_id": t.agent_id,
                "stock_symbol": t.stock_symbol,
                "direction": t.direction,
                "quantity": t.quantity,
                "buy_price": t.buy_price,
                "sell_price": t.sell_price,
                "purchase_date": t.purchase_date,
                "sell_date": t.sell_date,
                "exit_reason": t.exit_reason,
                "gross_profit": t.gross_profit,
                "charges": t.charges,
                "tax": t.tax,
                "net_profit": t.net_profit,
                "status": t.status,
                "is_manual": t.is_manual,
            }
            for t in rows
        ]
    )


@router.get("/kpis")
def kpis(include_manual: bool = True, db: Session = Depends(get_db)):
    df = _trades_df(db, include_manual)
    now = datetime.now(timezone.utc)

    def _in_this_month(d) -> bool:
        return d is not None and d.year == now.year and d.month == now.month

    # "Trades executed this month" and "capital invested this month" are
    # keyed off entry date (purchase_date) - that's when the trade/capital
    # commitment happened.
    entered_this_month = df["purchase_date"].apply(_in_this_month) if not df.empty else pd.Series(dtype=bool)

    closed = df[df["status"] == "closed"]
    # Realized P&L "this month" must be keyed off *exit* date (sell_date),
    # not entry date - a trade opened last month and closed this month
    # realizes its profit this month, not last month, and a trade opened
    # this month but still open has no realized profit yet at all.
    closed_this_month = (
        closed["sell_date"].apply(_in_this_month) if not closed.empty else pd.Series(dtype=bool)
    )

    return {
        "total_trades_all_time": int(len(df)),
        "total_trades_this_month": int(entered_this_month.sum()) if not df.empty else 0,
        "total_quantity_traded": int(df["quantity"].sum()) if not df.empty else 0,
        "total_net_profit_all_time": round(float(closed["net_profit"].sum()), 2) if not closed.empty else 0.0,
        "total_net_profit_this_month": round(
            float(closed[closed_this_month]["net_profit"].sum()), 2
        ) if not closed.empty else 0.0,
        "total_capital_invested_this_month": round(
            float((df[entered_this_month]["buy_price"] * df[entered_this_month]["quantity"]).sum()), 2
        ) if not df.empty else 0.0,
        "open_positions_count": int((df["status"] == "open").sum()) if not df.empty else 0,
        "total_charges_paid": round(float(closed["charges"].sum()), 2) if not closed.empty else 0.0,
        "total_tax_accrued": round(float(closed["tax"].sum()), 2) if not closed.empty else 0.0,
        # Capital is always account-wide (all trades, not just include_manual's
        # selection) since it's a real constraint on what can be traded at all.
        **get_capital_summary(db),
    }


@router.get("/profit-over-time")
def profit_over_time(
    granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    include_manual: bool = True,
    db: Session = Depends(get_db),
):
    df = _trades_df(db, include_manual)
    closed = df[df["status"] == "closed"].copy()
    if closed.empty:
        return []

    closed["sell_date"] = pd.to_datetime(closed["sell_date"])
    freq = {"daily": "D", "weekly": "W", "monthly": "MS"}[granularity]
    grouped = closed.set_index("sell_date").resample(freq)["net_profit"].sum().reset_index()
    return [
        {"period": row["sell_date"].strftime("%Y-%m-%d"), "net_profit": round(float(row["net_profit"]), 2)}
        for _, row in grouped.iterrows()
    ]


@router.get("/capital-per-month")
def capital_per_month(include_manual: bool = True, db: Session = Depends(get_db)):
    df = _trades_df(db, include_manual)
    if df.empty:
        return []
    df = df.copy()
    df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    df["capital"] = df["buy_price"] * df["quantity"]
    grouped = df.set_index("purchase_date").resample("MS")["capital"].sum().reset_index()
    return [
        {"month": row["purchase_date"].strftime("%Y-%m"), "capital": round(float(row["capital"]), 2)}
        for _, row in grouped.iterrows()
    ]


@router.get("/trade-frequency")
def trade_frequency(
    granularity: str = Query("week", pattern="^(week|month)$"),
    db: Session = Depends(get_db),
):
    df = _trades_df(db, include_manual=True)
    if df.empty:
        return []
    df = df.copy()
    df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    df["agent_label"] = df["agent_id"].fillna("manual")
    freq = "W" if granularity == "week" else "MS"
    grouped = (
        df.set_index("purchase_date")
        .groupby("agent_label")
        .resample(freq)["trade_id"]
        .count()
        .reset_index(name="count")
    )
    return [
        {
            "period": row["purchase_date"].strftime("%Y-%m-%d"),
            "agent_id": row["agent_label"],
            "count": int(row["count"]),
        }
        for _, row in grouped.iterrows()
        if row["count"] > 0
    ]


@router.get("/win-rate")
def win_rate(include_manual: bool = True, db: Session = Depends(get_db)):
    df = _trades_df(db, include_manual)
    closed = df[df["status"] == "closed"]
    if closed.empty:
        return {"target": 0, "stop_loss": 0, "manual": 0, "timeout": 0}
    counts = closed["exit_reason"].value_counts().to_dict()
    return {
        "target": int(counts.get("target", 0)),
        "stop_loss": int(counts.get("stop_loss", 0)),
        "manual": int(counts.get("manual", 0)),
        "timeout": int(counts.get("timeout", 0)),
    }


@router.get("/duration-metrics")
def duration_metrics(include_manual: bool = True, db: Session = Depends(get_db)):
    df = _trades_df(db, include_manual)
    closed = df[df["status"] == "closed"].copy()
    if closed.empty:
        return {"avg_hours_by_exit_reason": {}, "avg_hours_overall": 0.0, "histogram": {}}

    closed["purchase_date"] = pd.to_datetime(closed["purchase_date"])
    closed["sell_date"] = pd.to_datetime(closed["sell_date"])
    closed["duration_hours"] = (closed["sell_date"] - closed["purchase_date"]).dt.total_seconds() / 3600

    avg_by_reason = closed.groupby("exit_reason")["duration_hours"].mean().round(2).to_dict()

    buckets = [
        ("<1hr", lambda h: h < 1),
        ("1-4hrs", lambda h: 1 <= h < 4),
        ("4-24hrs", lambda h: 4 <= h < 24),
        ("1-3 days", lambda h: 24 <= h < 72),
        ("3+ days", lambda h: h >= 72),
    ]
    histogram = {
        label: int(closed["duration_hours"].apply(cond).sum()) for label, cond in buckets
    }

    return {
        "avg_hours_by_exit_reason": avg_by_reason,
        "avg_hours_overall": round(float(closed["duration_hours"].mean()), 2),
        "histogram": histogram,
    }


@router.get("/agents-breakdown")
def agents_breakdown(db: Session = Depends(get_db)):
    agents = db.query(Agent).all()
    df = _trades_df(db, include_manual=False)

    result = []
    for agent in agents:
        agent_trades = df[df["agent_id"] == agent.agent_id]
        closed = agent_trades[agent_trades["status"] == "closed"].copy()
        win_count = int((closed["exit_reason"] == "target").sum()) if not closed.empty else 0
        avg_duration = None
        if not closed.empty:
            closed["purchase_date"] = pd.to_datetime(closed["purchase_date"])
            closed["sell_date"] = pd.to_datetime(closed["sell_date"])
            avg_duration = round(
                float(((closed["sell_date"] - closed["purchase_date"]).dt.total_seconds() / 3600).mean()), 2
            )

        result.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "active": agent.active,
                "trades_count": int(len(agent_trades)),
                "win_rate_pct": round(win_count / len(closed) * 100, 1) if len(closed) > 0 else 0.0,
                "net_profit": round(float(closed["net_profit"].sum()), 2) if not closed.empty else 0.0,
                "avg_duration_hours": avg_duration,
            }
        )
    return result
