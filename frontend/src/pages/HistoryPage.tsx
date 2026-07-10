import TradeLogTable from "../components/TradeLogTable";

export default function HistoryPage({ refreshTick }: { refreshTick: number }) {
  return (
    <div className="section">
      <TradeLogTable key={`history-${refreshTick}`} lockedStatus="closed" title="Trade history" />
    </div>
  );
}
