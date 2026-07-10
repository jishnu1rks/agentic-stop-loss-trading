"""
Charges calculation (Section 6.3) - transactional cost of trading, kept
strictly separate from tax (see tax.py).

Assumption (ties to the Section 10 open item on short-selling): a `buy`
direction trade is treated as delivery (CNC - can be held multi-day until
GTT exit), and a `sell` (short) direction trade is treated as intraday
(MIS), since naked short selling in cash equities must be squared off
same-day on NSE. This changes which charge lines apply (delivery has zero
brokerage but STT on both legs; intraday has brokerage on both legs but
STT only on the sell leg). Rates approximate Zerodha's published NSE
equity charge structure and are estimates, not filing-ready figures.
"""
from dataclasses import dataclass

from app.config import settings


@dataclass
class ChargeBreakdown:
    brokerage: float
    stt: float
    exchange_txn: float
    sebi_charges: float
    stamp_duty: float
    gst: float

    @property
    def total(self) -> float:
        return round(
            self.brokerage
            + self.stt
            + self.exchange_txn
            + self.sebi_charges
            + self.stamp_duty
            + self.gst,
            2,
        )


def compute_charges(
    direction: str, buy_price: float, sell_price: float, quantity: int
) -> ChargeBreakdown:
    turnover_buy = buy_price * quantity
    turnover_sell = sell_price * quantity
    total_turnover = turnover_buy + turnover_sell
    is_delivery = direction == "buy"

    if is_delivery:
        brokerage = 0.0
        stt = total_turnover * settings.stt_delivery_pct
        stamp_duty = turnover_buy * settings.stamp_duty_buy_delivery_pct
    else:
        brokerage = min(settings.brokerage_pct * turnover_buy, settings.brokerage_cap) + min(
            settings.brokerage_pct * turnover_sell, settings.brokerage_cap
        )
        stt = turnover_sell * settings.stt_intraday_sell_pct
        stamp_duty = turnover_buy * settings.stamp_duty_buy_intraday_pct

    exchange_txn = total_turnover * settings.exchange_txn_pct
    sebi_charges = total_turnover * settings.sebi_charges_pct
    gst = (brokerage + exchange_txn + sebi_charges) * settings.gst_pct

    return ChargeBreakdown(
        brokerage=round(brokerage, 2),
        stt=round(stt, 2),
        exchange_txn=round(exchange_txn, 2),
        sebi_charges=round(sebi_charges, 2),
        stamp_duty=round(stamp_duty, 2),
        gst=round(gst, 2),
    )
