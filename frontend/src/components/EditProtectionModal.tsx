import { useState } from "react";
import { api } from "../api/client";
import type { OpenPositionPnl, Trade } from "../api/types";
import Modal from "./Modal";
import ProtectionField, { type ProtectionMode } from "./ProtectionField";
import {
  stopLossPctFromPrice,
  stopLossPriceFromPct,
  targetPctFromPrice,
  targetPriceFromPct,
} from "../lib/protection";

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
  const entry = trade.buy_price;

  const [slMode, setSlMode] = useState<ProtectionMode>("price");
  const [slValue, setSlValue] = useState<string>(trade.stop_loss_price ? String(trade.stop_loss_price) : "");
  const [tgtMode, setTgtMode] = useState<ProtectionMode>("price");
  const [tgtValue, setTgtValue] = useState<string>(trade.target_price != null ? String(trade.target_price) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slNum = Number(slValue);
  const slHasValue = slValue.trim() !== "" && !Number.isNaN(slNum) && slNum > 0;
  const slPrice = slHasValue ? (slMode === "price" ? slNum : stopLossPriceFromPct(trade.direction, entry, slNum)) : null;
  const slSecondary = slHasValue
    ? slMode === "price"
      ? `≈ ${stopLossPctFromPrice(entry, slNum).toFixed(2)}% from entry`
      : `≈ ₹${stopLossPriceFromPct(trade.direction, entry, slNum).toFixed(2)}`
    : undefined;

  const tgtNum = Number(tgtValue);
  const tgtHasValue = tgtValue.trim() !== "" && !Number.isNaN(tgtNum) && tgtNum > 0;
  const tgtPrice = tgtHasValue ? (tgtMode === "price" ? tgtNum : targetPriceFromPct(trade.direction, entry, tgtNum)) : null;
  const tgtSecondary = tgtHasValue
    ? tgtMode === "price"
      ? `≈ ${targetPctFromPrice(entry, tgtNum).toFixed(2)}% from entry`
      : `≈ ₹${targetPriceFromPct(trade.direction, entry, tgtNum).toFixed(2)}`
    : undefined;

  const handleSave = async () => {
    setError(null);
    if (slPrice == null || slPrice <= 0) {
      setError("Stop loss must be a positive number.");
      return;
    }
    if (tgtValue.trim() !== "" && (tgtPrice == null || tgtPrice <= 0)) {
      setError("Target must be a positive number, or left blank to remove it.");
      return;
    }

    setSaving(true);
    try {
      await api.editProtection(trade.trade_id, {
        stop_loss_price: Math.round(slPrice * 100) / 100,
        target_price: tgtValue.trim() === "" ? null : Math.round(tgtPrice! * 100) / 100,
      });
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

      <ProtectionField
        label="Stop loss"
        mode={slMode}
        value={slValue}
        onModeChange={setSlMode}
        onValueChange={setSlValue}
        secondaryText={slSecondary}
        hint={trade.direction === "buy" ? "Must be below the buy price." : "Must be above the entry price."}
      />

      <ProtectionField
        label="Target"
        mode={tgtMode}
        value={tgtValue}
        onModeChange={setTgtMode}
        onValueChange={setTgtValue}
        secondaryText={tgtSecondary}
        hint="Leave blank to remove the target (stop-loss only)."
        optional
      />
    </Modal>
  );
}
