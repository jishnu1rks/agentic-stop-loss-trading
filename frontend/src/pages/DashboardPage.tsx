import RecommendationsPanel from "../components/RecommendationsPanel";

export default function DashboardPage({ onChanged }: { onChanged: () => void }) {
  return (
    <div className="section">
      <RecommendationsPanel onBought={onChanged} />
    </div>
  );
}
