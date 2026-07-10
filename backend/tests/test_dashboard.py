from datetime import datetime, timedelta, timezone

from app.models import Trade
from app.routers.dashboard import kpis


def _make_trade(purchase_date, sell_date, net_profit, status="closed", **overrides):
    defaults = dict(
        stock_symbol="TEST",
        direction="buy",
        quantity=10,
        buy_price=100.0,
        sell_price=110.0 if status == "closed" else None,
        purchase_date=purchase_date,
        sell_date=sell_date,
        stop_loss_pct=2.0,
        stop_loss_price=98.0,
        gross_profit=100.0 if status == "closed" else None,
        charges=5.0 if status == "closed" else None,
        tax=0.0 if status == "closed" else None,
        net_profit=net_profit,
        status=status,
        is_manual=True,
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_net_profit_this_month_uses_exit_date_not_entry_date(db_session):
    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=1)

    # Opened last month, closed this month -> profit IS realized this month.
    db_session.add(_make_trade(purchase_date=last_month, sell_date=now, net_profit=500.0))
    # Opened this month, still open -> no realized profit at all yet.
    db_session.add(_make_trade(purchase_date=now, sell_date=None, net_profit=None, status="open"))
    db_session.commit()

    result = kpis(include_manual=True, db=db_session)

    assert result["total_net_profit_this_month"] == 500.0
    assert result["total_net_profit_all_time"] == 500.0
    assert result["total_trades_this_month"] == 1  # only the one entered this month
    assert result["total_trades_all_time"] == 2
    assert result["open_positions_count"] == 1


def test_net_profit_this_month_excludes_trades_closed_last_month(db_session):
    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=1)

    # Opened and closed entirely last month -> should not count toward this month.
    db_session.add(_make_trade(purchase_date=last_month, sell_date=last_month, net_profit=300.0))
    db_session.commit()

    result = kpis(include_manual=True, db=db_session)

    assert result["total_net_profit_this_month"] == 0.0
    assert result["total_net_profit_all_time"] == 300.0


def test_charges_and_tax_are_summed_separately(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(_make_trade(purchase_date=now, sell_date=now, net_profit=80.0, charges=15.0, tax=5.0))
    db_session.add(_make_trade(purchase_date=now, sell_date=now, net_profit=40.0, charges=10.0, tax=2.0))
    db_session.commit()

    result = kpis(include_manual=True, db=db_session)

    assert result["total_charges_paid"] == 25.0
    assert result["total_tax_accrued"] == 7.0
    assert result["total_net_profit_all_time"] == 120.0
