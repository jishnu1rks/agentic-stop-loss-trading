import { useState } from "react";
import TradeLogTable from "../components/TradeLogTable";
import AddTradeModal from "../components/AddTradeModal";

export default function OpenTradesPage({ refreshTick, onChanged }: { refreshTick: number; onChanged: () => void }) {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="section">
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
