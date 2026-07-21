import type { Direction } from "../api/types";

// Mirrors backend compute_charges (app/charges.py) so the "include charges"
// toggle in EditProtectionModal can show a net-of-charges %/price without a
// round-trip to the server - same estimated Zerodha-style NSE equity rates
// the backend uses. Tax is intentionally excluded (charges/fees only, per
// the trade_charges endpoint's own brokerage/STT/exchange/SEBI/stamp/GST split).
const BROKERAGE_PCT = 0.0003;
const BROKERAGE_CAP = 20.0;
const STT_DELIVERY_PCT = 0.001;
const STT_INTRADAY_SELL_PCT = 0.00025;
const EXCHANGE_TXN_PCT = 0.0000297;
const SEBI_CHARGES_PCT = 0.0000001;
const STAMP_DUTY_BUY_DELIVERY_PCT = 0.00015;
const STAMP_DUTY_BUY_INTRADAY_PCT = 0.00003;
const GST_PCT = 0.18;

function estimateCharges(direction: Direction, buyPrice: number, sellPrice: number, quantity: number): number {
  const turnoverBuy = buyPrice * quantity;
  const turnoverSell = sellPrice * quantity;
  const totalTurnover = turnoverBuy + turnoverSell;
  const isDelivery = direction === "buy"; // buy = delivery (CNC), sell = intraday (MIS) - same assumption as charges.py

  let brokerage = 0;
  let stt: number;
  let stampDuty: number;

  if (isDelivery) {
    stt = totalTurnover * STT_DELIVERY_PCT;
    stampDuty = turnoverBuy * STAMP_DUTY_BUY_DELIVERY_PCT;
  } else {
    brokerage =
      Math.min(BROKERAGE_PCT * turnoverBuy, BROKERAGE_CAP) + Math.min(BROKERAGE_PCT * turnoverSell, BROKERAGE_CAP);
    stt = turnoverSell * STT_INTRADAY_SELL_PCT;
    stampDuty = turnoverBuy * STAMP_DUTY_BUY_INTRADAY_PCT;
  }

  const exchangeTxn = totalTurnover * EXCHANGE_TXN_PCT;
  const sebiCharges = totalTurnover * SEBI_CHARGES_PCT;
  const gst = (brokerage + exchangeTxn + sebiCharges) * GST_PCT;

  return brokerage + stt + exchangeTxn + sebiCharges + stampDuty + gst;
}

// A target/stop-loss price move still loses a bit more (or gains a bit
// less) once brokerage/STT/exchange/SEBI/stamp duty/GST are deducted at
// exit - this is the % actually realized after those charges, not the raw
// price-move %.
export function netPctAfterCharges(direction: Direction, buyPrice: number, exitPrice: number, quantity: number): number {
  const investedValue = buyPrice * quantity;
  if (!investedValue) return 0;
  const grossProfit = direction === "buy" ? (exitPrice - buyPrice) * quantity : (buyPrice - exitPrice) * quantity;
  const charges = estimateCharges(direction, buyPrice, exitPrice, quantity);
  return ((grossProfit - charges) / investedValue) * 100;
}
