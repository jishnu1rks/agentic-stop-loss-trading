import type { Direction } from "../api/types";

// Mirrors backend stop_loss_price()/target_price() (agent_runtime.py) so the
// pct <-> price toggle in the UI shows numbers consistent with what the
// server will actually compute/validate.

export function stopLossPriceFromPct(direction: Direction, entry: number, pct: number): number {
  return direction === "buy" ? entry * (1 - pct / 100) : entry * (1 + pct / 100);
}

export function stopLossPctFromPrice(entry: number, price: number): number {
  return entry ? (Math.abs(entry - price) / entry) * 100 : 0;
}

export function targetPriceFromPct(direction: Direction, entry: number, pct: number): number {
  return direction === "buy" ? entry * (1 + pct / 100) : entry * (1 - pct / 100);
}

export function targetPctFromPrice(entry: number, price: number): number {
  return entry ? (Math.abs(price - entry) / entry) * 100 : 0;
}
