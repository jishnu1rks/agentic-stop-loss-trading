import { useState } from "react";
import type { Kpis } from "../api/types";
import KpiCards from "../components/KpiCards";
import TradeLogTable from "../components/TradeLogTable";
import AddTradeModal from "../components/AddTradeModal";

export default function OpenTradesPage({
  refreshTick,
  onChanged,
  kpis,
}: {
  refreshTick: number;
  onChanged: () => void;
  kpis: Kpis | null;
}) {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="section">
      {kpis && (
        <div style={{ marginBottom: 20 }}>
          <KpiCards kpis={kpis} />
        </div>
      )}
      <div className="section-header-row">
        <button className="btn btn-buy" onClick={() => setShowAdd(true)}>
          Manual +
        </button>
      </div>
      <TradeLogTable key={`open-${refreshTick}`} lockedStatus="open" onChanged={onChanged} />
      {showAdd && <AddTradeModal onClose={() => setShowAdd(false)} onSaved={onChanged} />}
    </div>
  );
}
