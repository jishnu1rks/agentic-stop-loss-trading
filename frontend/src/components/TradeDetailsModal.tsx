import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChargesBreakdown, OpenPositionPnl, Trade } from "../api/types";
import Modal from "./Modal";

function fmtDateOnly(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { dateStyle: "medium" });
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

  return (
    <Modal title={`${trade.stock_symbol} — trade details`} onClose={onClose}>
      {loading && <div className="empty-state">Loading…</div>}
      {error && <div className="error-banner">{error}</div>}
      {data && (
        <>
          <dl className="detail-rows">
            <dt>Direction</dt>
            <dd>{trade.direction}</dd>
            <dt>Mode</dt>
            <dd>{trade.is_manual ? "Manual" : agentName}</dd>
            <dt>Quantity</dt>
            <dd>{trade.quantity}</dd>
            <dt>Buy price</dt>
            <dd>{trade.buy_price.toFixed(2)}</dd>
            <dt>Buy date</dt>
            <dd>{fmtDateOnly(trade.purchase_date)}</dd>
            {trade.status === "open" ? (
              <>
                <dt>CMP</dt>
                <dd>{pnl ? pnl.current_price.toFixed(2) : "—"}</dd>
              </>
            ) : (
              <>
                <dt>Sell price</dt>
                <dd>{trade.sell_price != null ? trade.sell_price.toFixed(2) : "—"}</dd>
                <dt>Sell date</dt>
                <dd>{fmtDateOnly(trade.sell_date)}</dd>
              </>
            )}
            <dt>Stop loss</dt>
            <dd>
              {trade.stop_loss_price
                ? `${trade.stop_loss_price.toFixed(2)}${trade.stop_loss_pct ? ` (-${trade.stop_loss_pct.toFixed(1)}%)` : ""}`
                : "—"}
            </dd>
            <dt>Target</dt>
            <dd>
              {trade.target_price != null
                ? `${trade.target_price.toFixed(2)}${trade.target_pct != null ? ` (${trade.target_pct.toFixed(1)}%)` : ""}`
                : "—"}
            </dd>
            <dt>Investment</dt>
            <dd>{(trade.buy_price * trade.quantity).toFixed(2)}</dd>
          </dl>

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
