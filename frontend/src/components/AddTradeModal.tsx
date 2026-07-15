import { useState } from "react";
import { api } from "../api/client";
import type { Direction, Quote } from "../api/types";
import Modal from "./Modal";
import ProtectionField, { type ProtectionMode } from "./ProtectionField";
import {
  stopLossPctFromPrice,
  stopLossPriceFromPct,
  targetPctFromPrice,
  targetPriceFromPct,
} from "../lib/protection";

function detailFromApiError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail ?? fallback;
}

export default function AddTradeModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);

  const [direction, setDirection] = useState<Direction>("buy");
  const [quantity, setQuantity] = useState("1");

  const [slMode, setSlMode] = useState<ProtectionMode>("pct");
  const [slValue, setSlValue] = useState("2");
  const [tgtMode, setTgtMode] = useState<ProtectionMode>("pct");
  const [tgtValue, setTgtValue] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLookup = async () => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setQuoteLoading(true);
    setQuoteError(null);
    setQuote(null);
    try {
      setQuote(await api.getQuote(sym));
    } catch (e: unknown) {
      setQuoteError(detailFromApiError(e, `Could not fetch a price for ${sym}.`));
    } finally {
      setQuoteLoading(false);
    }
  };

  const entry = quote?.price ?? null;

  const slNum = Number(slValue);
  const slHasValue = slValue.trim() !== "" && !Number.isNaN(slNum) && slNum > 0;
  const slPrice = entry != null && slHasValue ? (slMode === "price" ? slNum : stopLossPriceFromPct(direction, entry, slNum)) : null;
  const slSecondary =
    entry != null && slHasValue
      ? slMode === "price"
        ? `≈ ${stopLossPctFromPrice(entry, slNum).toFixed(2)}% from CMP`
        : `≈ ₹${stopLossPriceFromPct(direction, entry, slNum).toFixed(2)}`
      : undefined;

  const tgtNum = Number(tgtValue);
  const tgtHasValue = tgtValue.trim() !== "" && !Number.isNaN(tgtNum) && tgtNum > 0;
  const tgtPrice = entry != null && tgtHasValue ? (tgtMode === "price" ? tgtNum : targetPriceFromPct(direction, entry, tgtNum)) : null;
  const tgtSecondary =
    entry != null && tgtHasValue
      ? tgtMode === "price"
        ? `≈ ${targetPctFromPrice(entry, tgtNum).toFixed(2)}% from CMP`
        : `≈ ₹${targetPriceFromPct(direction, entry, tgtNum).toFixed(2)}`
      : undefined;

  const qtyNum = Number(quantity);
  const qtyValid = quantity.trim() !== "" && Number.isInteger(qtyNum) && qtyNum > 0;

  const handleSubmit = async () => {
    setError(null);
    if (!quote || entry == null) {
      setError("Look up a price for the ticker first.");
      return;
    }
    if (!qtyValid) {
      setError("Quantity must be a positive whole number.");
      return;
    }
    if (slValue.trim() !== "" && !slHasValue) {
      setError("Stop loss must be a positive number, or left blank to skip it.");
      return;
    }
    if (tgtValue.trim() !== "" && !tgtHasValue) {
      setError("Target must be a positive number, or left blank to skip it.");
      return;
    }

    const stopLossPct = slHasValue ? (slMode === "pct" ? slNum : stopLossPctFromPrice(entry, slNum)) : undefined;
    const targetPct = tgtHasValue ? (tgtMode === "pct" ? tgtNum : targetPctFromPrice(entry, tgtNum)) : undefined;

    setSubmitting(true);
    try {
      await api.placeManualTrade({
        stock_symbol: quote.symbol,
        direction,
        quantity: qtyNum,
        stop_loss_pct: stopLossPct,
        target_pct: targetPct,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError(detailFromApiError(e, "Failed to add the trade."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="Add manual trade"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-neutral" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button className="btn btn-buy" onClick={handleSubmit} disabled={submitting || !quote}>
            {submitting ? "Adding…" : "Add trade"}
          </button>
        </>
      }
    >
      {error && <div className="error-banner">{error}</div>}

      <div className="modal-field">
        <label>Stock ticker</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLookup()}
            placeholder="e.g. RELIANCE.NS"
            autoFocus
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="btn btn-neutral"
            onClick={handleLookup}
            disabled={quoteLoading || !symbol.trim()}
          >
            {quoteLoading ? "Looking up…" : "Get price"}
          </button>
        </div>
        {quoteError && (
          <span className="field-hint text-red">{quoteError}</span>
        )}
      </div>

      {quote && (
        <>
          <dl className="detail-rows" style={{ marginBottom: 14 }}>
            <dt>Symbol</dt>
            <dd>{quote.symbol}</dd>
            <dt>Current price</dt>
            <dd>₹{quote.price.toFixed(2)}</dd>
          </dl>

          <div className="modal-field">
            <label>Direction</label>
            <select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
              <option value="buy">Buy</option>
              <option value="sell">Sell (short)</option>
            </select>
          </div>

          <div className="modal-field">
            <label>Quantity</label>
            <input type="number" step="1" min="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </div>

          <ProtectionField
            label="Stop loss"
            mode={slMode}
            value={slValue}
            onModeChange={setSlMode}
            onValueChange={setSlValue}
            secondaryText={slSecondary}
            hint={
              slPrice != null
                ? `Exits at ₹${slPrice.toFixed(2)}. ${direction === "buy" ? "Below" : "Above"} the entry price.`
                : "Leave blank to skip a stop-loss (not recommended)."
            }
            optional
          />

          <ProtectionField
            label="Target"
            mode={tgtMode}
            value={tgtValue}
            onModeChange={setTgtMode}
            onValueChange={setTgtValue}
            secondaryText={tgtSecondary}
            hint={tgtPrice != null ? `Exits at ₹${tgtPrice.toFixed(2)}.` : "Leave blank to skip a target."}
            optional
          />
        </>
      )}
    </Modal>
  );
}
