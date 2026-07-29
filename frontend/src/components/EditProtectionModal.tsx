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
import { netPctAfterCharges } from "../lib/charges";

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

function fmtInr(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`;
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

  // Single shared mode for both fields (rather than one toggle each) - the
  // point of showing stop-loss and target side by side is comparing the
  // two bounds directly, which only works cleanly when they're in the same
  // unit at a glance.
  const [mode, setMode] = useState<ProtectionMode>("price");
  const [slValue, setSlValue] = useState<string>(trade.stop_loss_price ? String(trade.stop_loss_price) : "");
  const [tgtValue, setTgtValue] = useState<string>(trade.target_price != null ? String(trade.target_price) : "");
  const [includeCharges, setIncludeCharges] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleModeChange = (m: ProtectionMode) => {
    const slNum = Number(slValue);
    if (slValue.trim() !== "" && !Number.isNaN(slNum) && slNum > 0) {
      const converted =
        m === "pct" ? stopLossPctFromPrice(entry, slNum) : stopLossPriceFromPct(trade.direction, entry, slNum);
      setSlValue(converted.toFixed(2));
    }
    const tgtNum = Number(tgtValue);
    if (tgtValue.trim() !== "" && !Number.isNaN(tgtNum) && tgtNum > 0) {
      const converted = m === "pct" ? targetPctFromPrice(entry, tgtNum) : targetPriceFromPct(trade.direction, entry, tgtNum);
      setTgtValue(converted.toFixed(2));
    }
    setMode(m);
  };

  const slNum = Number(slValue);
  const slHasValue = slValue.trim() !== "" && !Number.isNaN(slNum) && slNum > 0;
  const slPrice = slHasValue ? (mode === "price" ? slNum : stopLossPriceFromPct(trade.direction, entry, slNum)) : null;
  const slSecondary = slHasValue
    ? (mode === "price"
        ? `≈ ${stopLossPctFromPrice(entry, slNum).toFixed(2)}% from entry`
        : `≈ ${stopLossPriceFromPct(trade.direction, entry, slNum).toFixed(2)}`) +
      (includeCharges && slPrice != null
        ? ` · net of charges ≈ ${netPctAfterCharges(trade.direction, entry, slPrice, trade.quantity).toFixed(2)}%`
        : "")
    : undefined;

  const tgtNum = Number(tgtValue);
  const tgtHasValue = tgtValue.trim() !== "" && !Number.isNaN(tgtNum) && tgtNum > 0;
  const tgtPrice = tgtHasValue ? (mode === "price" ? tgtNum : targetPriceFromPct(trade.direction, entry, tgtNum)) : null;
  const tgtSecondary = tgtHasValue
    ? (mode === "price"
        ? `≈ ${targetPctFromPrice(entry, tgtNum).toFixed(2)}% from entry`
        : `≈ ${targetPriceFromPct(trade.direction, entry, tgtNum).toFixed(2)}`) +
      (includeCharges && tgtPrice != null
        ? ` · net of charges ≈ ${netPctAfterCharges(trade.direction, entry, tgtPrice, trade.quantity).toFixed(2)}%`
        : "")
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
      ? `${pnl.unrealized_pnl.toFixed(2)} (${pnl.unrealized_pnl_pct >= 0 ? "+" : ""}${pnl.unrealized_pnl_pct.toFixed(1)}%)`
      : "—";

  const handleCopy = () => {
    const lines = [
      `${trade.stock_symbol} ${trade.direction.toUpperCase()} OPEN (${trade.is_manual ? "Manual" : agentName})`,
      `Qty: ${trade.quantity}  Buy: ${trade.buy_price.toFixed(2)}  CMP: ${pnl ? pnl.current_price.toFixed(2) : "—"}  P&L: ${
        pnl ? fmtInr(pnl.unrealized_pnl) : "—"
      }`,
      `Entry: ${fmtDate(trade.purchase_date)}`,
    ];
    navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

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
      <div className="trade-summary-card">
        <div className="tsc-header">
          {/* No ticker here - the modal title bar already shows it. */}
          <span className="text-dim" style={{ fontSize: 11 }}>
            {trade.is_manual ? "Manual" : agentName}
          </span>
          <span className="tsc-spacer" />
          <span className={`tsc-direction ${trade.direction}`}>
            <span className={`tsc-dot ${trade.direction}`} />
            {trade.direction.toUpperCase()}
          </span>
          <button className="tsc-copy" onClick={handleCopy} title="Copy summary">
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
          <span className="tsc-status">OPEN</span>
        </div>

        <div className="tsc-divider" />

        <div className="tsc-stats">
          <div className="tsc-stat">
            <span className="tsc-label">Qty</span>
            <span className="tsc-value">{trade.quantity}</span>
          </div>
          <div className="tsc-stat">
            <span className="tsc-label">Buy</span>
            <span className="tsc-value">{trade.buy_price.toFixed(2)}</span>
          </div>
          <div className="tsc-stat">
            <span className="tsc-label">CMP</span>
            <span className="tsc-value">{pnl != null ? pnl.current_price.toFixed(2) : "—"}</span>
          </div>
          <div className="tsc-stat">
            <span className="tsc-label">P&amp;L</span>
            <span className="tsc-value">
              {pnl != null && (
                <span
                  className="tsc-dot"
                  style={{ background: pnl.unrealized_pnl >= 0 ? "var(--green)" : "var(--red)" }}
                />
              )}
              {pnlText}
            </span>
          </div>
        </div>

        <div className="tsc-divider" />

        <div className="tsc-footer">
          <span>Entry: {fmtDate(trade.purchase_date)}</span>
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--panel-border)", margin: "14px 0" }} />

      {error && <div className="error-banner">{error}</div>}

      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 14 }}>
        <input type="checkbox" checked={includeCharges} onChange={(e) => setIncludeCharges(e.target.checked)} />
        Include brokerage &amp; other charges in the %/price shown below
      </label>

      <div className="mode-toggle" style={{ marginBottom: 10 }}>
        <button type="button" className={mode === "price" ? "active" : ""} onClick={() => handleModeChange("price")}>
          Price
        </button>
        <button type="button" className={mode === "pct" ? "active" : ""} onClick={() => handleModeChange("pct")}>
          %
        </button>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ProtectionField
            label="Stop loss"
            mode={mode}
            value={slValue}
            onModeChange={handleModeChange}
            onValueChange={setSlValue}
            secondaryText={slSecondary}
            hint={trade.direction === "buy" ? "Must be below the buy price." : "Must be above the entry price."}
            showModeToggle={false}
          />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <ProtectionField
            label="Target"
            mode={mode}
            value={tgtValue}
            onModeChange={handleModeChange}
            onValueChange={setTgtValue}
            secondaryText={tgtSecondary}
            hint="Leave blank to remove the target (stop-loss only)."
            showModeToggle={false}
          />
        </div>
      </div>
    </Modal>
  );
}
