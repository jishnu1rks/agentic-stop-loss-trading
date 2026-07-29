import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChargesBreakdown, OpenPositionPnl, Trade } from "../api/types";
import Modal from "./Modal";

function fmtDateTime(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

function fmtInr(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`;
}

function fmtDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const startMs = new Date(start).getTime();
  const endMs = end ? new Date(end).getTime() : Date.now();
  const totalMinutes = Math.max(0, Math.round((endMs - startMs) / 60_000));
  if (totalMinutes < 60) return `${totalMinutes} min${totalMinutes === 1 ? "" : "s"}`;
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  return mins === 0 ? `${hours}h` : `${hours}h ${mins}m`;
}

export default function TradeDetailsModal({
  trade,
  pnl,
  agentName,
  onClose,
}: {
  trade: Trade;
  pnl?: OpenPositionPnl;
  agentName: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<ChargesBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getTradeCharges(trade.trade_id)
      .then(setData)
      .catch((e: unknown) => {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(detail ?? "Could not load trade details.");
      })
      .finally(() => setLoading(false));
  }, [trade.trade_id]);

  const isOpen = trade.status === "open";
  const investment = trade.buy_price * trade.quantity;

  const handleCopy = (netProfit: number) => {
    const lines = [
      `${trade.stock_symbol} ${trade.direction.toUpperCase()} ${trade.status.toUpperCase()} (${trade.is_manual ? "Manual" : agentName})`,
      `Qty: ${trade.quantity}  Buy: ${trade.buy_price.toFixed(2)}  ${isOpen ? "CMP" : "Sell"}: ${
        isOpen ? (pnl ? pnl.current_price.toFixed(2) : "—") : trade.sell_price != null ? trade.sell_price.toFixed(2) : "—"
      }  Stop Loss: ${trade.stop_loss_price ? trade.stop_loss_price.toFixed(2) : "—"}  Target: ${
        trade.target_price != null ? trade.target_price.toFixed(2) : "—"
      }`,
      `Investment: ${fmtInr(investment)}  P&L: ${fmtInr(netProfit)}  Duration: ${fmtDuration(trade.purchase_date, trade.sell_date)}`,
      `Entry: ${fmtDateTime(trade.purchase_date)}   Exit: ${isOpen ? "still open" : fmtDateTime(trade.sell_date)}`,
    ];
    navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <Modal title={`${trade.stock_symbol} — trade details`} onClose={onClose}>
      {loading && <div className="empty-state">Loading…</div>}
      {error && <div className="error-banner">{error}</div>}
      {data && (
        <>
          <div className="trade-summary-card">
            <div className="tsc-header">
              {/* No ticker/agent name here - the modal title bar already
                  shows the ticker, and the row behind this modal already
                  shows the agent, so repeating either here is pure noise. */}
              <span className={`tsc-direction ${trade.direction}`}>
                <span className={`tsc-dot ${trade.direction}`} />
                {trade.direction.toUpperCase()}
              </span>
              <span className="tsc-spacer" />
              <button className="tsc-copy" onClick={() => handleCopy(data.net_profit)} title="Copy summary">
                {copied ? (
                  "✓"
                ) : (
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
                    <path
                      d="M3.5 10.5h-1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v1"
                      stroke="currentColor"
                      strokeWidth="1.3"
                    />
                  </svg>
                )}
              </button>
              <span className="tsc-status">{trade.status.toUpperCase()}</span>
            </div>

            <div className="tsc-divider" />

            <div className="tsc-stats">
              <div className="tsc-stat">
                <span className="tsc-label">Buy</span>
                <span className="tsc-value">{trade.buy_price.toFixed(2)}</span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">{isOpen ? "CMP" : "Sell"}</span>
                <span className="tsc-value">
                  {isOpen
                    ? pnl
                      ? pnl.current_price.toFixed(2)
                      : "—"
                    : trade.sell_price != null
                      ? trade.sell_price.toFixed(2)
                      : "—"}
                </span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">Stop Loss</span>
                <span className="tsc-value">{trade.stop_loss_price ? trade.stop_loss_price.toFixed(2) : "—"}</span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">Target</span>
                <span className="tsc-value">{trade.target_price != null ? trade.target_price.toFixed(2) : "—"}</span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">Qty</span>
                <span className="tsc-value">{trade.quantity}</span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">Investment</span>
                <span className="tsc-value">{fmtInr(investment)}</span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">P&amp;L</span>
                <span className="tsc-value">
                  <span
                    className="tsc-dot"
                    style={{ background: data.net_profit >= 0 ? "var(--green)" : "var(--red)" }}
                  />
                  {fmtInr(data.net_profit)}
                </span>
              </div>
              <div className="tsc-stat">
                <span className="tsc-label">Duration</span>
                <span className="tsc-value">{fmtDuration(trade.purchase_date, trade.sell_date)}</span>
              </div>
            </div>

            <div className="tsc-divider" />

            <div className="tsc-footer">
              <span>Entry: {fmtDateTime(trade.purchase_date)}</span>
              <span>Exit: {isOpen ? "still open" : fmtDateTime(trade.sell_date)}</span>
            </div>
          </div>

          <div style={{ borderTop: "1px solid var(--panel-border)", margin: "14px 0" }} />

          {data.is_estimate && (
            <div className="field-hint" style={{ marginBottom: 10 }}>
              Estimated as if this position were closed right now at {data.reference_price.toFixed(2)}.
            </div>
          )}

          <dl className="detail-rows">
            <dt>Gross P&amp;L</dt>
            <dd className={data.gross_profit >= 0 ? "text-green" : "text-red"}>{data.gross_profit.toFixed(2)}</dd>
            <dt>Charges</dt>
            <dd>{data.total_charges.toFixed(2)}</dd>
            <dt>Tax</dt>
            <dd>{data.tax.toFixed(2)}</dd>
            <dt>Net P&amp;L</dt>
            <dd className={data.net_profit >= 0 ? "text-green" : "text-red"}>{data.net_profit.toFixed(2)}</dd>
          </dl>
        </>
      )}
    </Modal>
  );
}
