import TradeLogTable from "../components/TradeLogTable";

export default function OpenTradesPage({ refreshTick, onChanged }: { refreshTick: number; onChanged: () => void }) {
  return (
    <div className="section">
      <TradeLogTable key={`open-${refreshTick}`} lockedStatus="open" onChanged={onChanged} />
    </div>
  );
}
