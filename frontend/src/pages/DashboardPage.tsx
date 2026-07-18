import type { Kpis } from "../api/types";
import KpiCards from "../components/KpiCards";
import RecommendationsPanel from "../components/RecommendationsPanel";

export default function DashboardPage({
  kpis,
  onChanged,
}: {
  kpis: Kpis | null;
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
        <RecommendationsPanel onBought={onChanged} />
      </div>
    </>
  );
}
