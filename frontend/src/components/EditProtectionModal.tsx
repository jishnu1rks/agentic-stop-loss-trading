import { useState } from "react";
import { api } from "../api/client";
import type { OpenPositionPnl, Trade } from "../api/types";
import Modal from "./Modal";

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export default function EditProtectionModal({
  trade,
  pnl,
  agentName,
  onClose,
  onSaved,
}: {
  trade: Trade;
  pnl?: OpenPositionPnl;
  agentName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [stopLoss, setStopLoss] = useState<string>(trade.stop_loss_price ? String(trade.stop_loss_price) : "");
  const [target, setTarget] = useState<string>(trade.target_price != null ? String(trade.target_price) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setError(null);
    const sl = Number(stopLoss);
    if (!stopLoss || Number.isNaN(sl) || sl <= 0) {
      setError("Stop loss must be a positive number.");
      return;
    }
    const tgt = target.trim() === "" ? null : Number(target);
    if (tgt !== null && (Number.isNaN(tgt) || tgt <= 0)) {
      setError("Target must be a positive number, or left blank to remove it.");
      return;
    }

    setSaving(true);
    try {
      await api.editProtection(trade.trade_id, { stop_loss_price: sl, target_price: tgt });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "Could not update the position.");
    } finally {
      setSaving(false);
    }
  };

  const pnlText =
    pnl != null
      ? `₹${pnl.unrealized_pnl.toFixed(2)} (${pnl.unrealized_pnl_pct >= 0 ? "+" : ""}${pnl.unrealized_pnl_pct.toFixed(1)}%)`
      : "—";

  return (
    <Modal
      title={`Edit ${trade.stock_symbol} position`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-neutral" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-buy" onClick={handleSave} disabled={saving}>
            {saving ? "Updating…" : "Update"}
          </button>
        </>
      }
    >
      <dl className="detail-rows">
        <dt>Symbol</dt>
        <dd>
          {trade.stock_symbol} {trade.is_manual && <span className="pill manual">manual</span>}
        </dd>
        <dt>Direction</dt>
        <dd>
          <span className={`pill ${trade.direction}`}>{trade.direction}</span>
        </dd>
        <dt>Quantity</dt>
        <dd>{trade.quantity}</dd>
        <dt>Buy price</dt>
        <dd>₹{trade.buy_price.toFixed(2)}</dd>
        <dt>Current price</dt>
        <dd>{pnl != null ? `₹${pnl.current_price.toFixed(2)}` : "—"}</dd>
        <dt>Unrealized P&amp;L</dt>
        <dd className={pnl != null ? (pnl.unrealized_pnl >= 0 ? "text-green" : "text-red") : ""}>{pnlText}</dd>
        <dt>Agent</dt>
        <dd>{agentName}</dd>
        <dt>Purchase date</dt>
        <dd>{fmtDate(trade.purchase_date)}</dd>
      </dl>

      <div style={{ borderTop: "1px solid var(--panel-border)", margin: "14px 0" }} />

      {error && <div className="error-banner">{error}</div>}

      <div className="modal-field">
        <label>Stop loss (₹)</label>
        <input
          type="number"
          step="0.05"
          value={stopLoss}
          onChange={(e) => setStopLoss(e.target.value)}
          autoFocus
        />
        <span className="field-hint">
          {trade.direction === "buy" ? "Must be below the buy price." : "Must be above the entry price."}
        </span>
      </div>

      <div className="modal-field">
        <label>Target (₹)</label>
        <input type="number" step="0.05" value={target} onChange={(e) => setTarget(e.target.value)} />
        <span className="field-hint">Leave blank to remove the target (stop-loss only).</span>
      </div>
    </Modal>
  );
}
