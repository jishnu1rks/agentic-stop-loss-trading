import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChargesBreakdown, Trade } from "../api/types";
import Modal from "./Modal";

export default function ChargesBreakdownModal({ trade, onClose }: { trade: Trade; onClose: () => void }) {
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
        setError(detail ?? "Could not load the charges breakdown.");
      })
      .finally(() => setLoading(false));
  }, [trade.trade_id]);

  return (
    <Modal title={`${trade.stock_symbol} — charges & tax breakdown`} onClose={onClose}>
      {loading && <div className="empty-state">Loading…</div>}
      {error && <div className="error-banner">{error}</div>}
      {data && (
        <>
          {data.is_estimate && (
            <div className="field-hint" style={{ marginBottom: 10 }}>
              Estimated as if this position were closed right now at {data.reference_price.toFixed(2)} - actual
              charges are only finalized once the position closes.
            </div>
          )}

          <dl className="detail-rows">
            <dt>Brokerage</dt>
            <dd>{data.brokerage.toFixed(2)}</dd>
            <dt>STT</dt>
            <dd>{data.stt.toFixed(2)}</dd>
            <dt>Exchange txn charges</dt>
            <dd>{data.exchange_txn.toFixed(2)}</dd>
            <dt>SEBI charges</dt>
            <dd>{data.sebi_charges.toFixed(2)}</dd>
            <dt>Stamp duty</dt>
            <dd>{data.stamp_duty.toFixed(2)}</dd>
            <dt>GST</dt>
            <dd>{data.gst.toFixed(2)}</dd>
            <dt>Total charges</dt>
            <dd>{data.total_charges.toFixed(2)}</dd>
            <dt>Estimated tax</dt>
            <dd>{data.tax.toFixed(2)}</dd>
          </dl>
        </>
      )}
    </Modal>
  );
}
