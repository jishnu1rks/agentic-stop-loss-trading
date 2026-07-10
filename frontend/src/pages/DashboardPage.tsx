import type { Kpis } from "../api/types";
import KpiCards from "../components/KpiCards";
import RecommendationsPanel from "../components/RecommendationsPanel";

export default function DashboardPage({
  kpis,
  refreshTick,
  onChanged,
}: {
  kpis: Kpis | null;
  refreshTick: number;
  onChanged: () => void;
}) {
  return (
    <>
      {kpis && (
        <div className="section">
          <KpiCards kpis={kpis} />
        </div>
      )}
      <div className="section">
        <RecommendationsPanel key={`reco-${refreshTick}`} onBought={onChanged} />
      </div>
    </>
  );
}
