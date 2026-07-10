import type { AgentBreakdown } from "../api/types";

export default function AgentTable({ agents }: { agents: AgentBreakdown[] }) {
  return (
    <div className="panel">
      {agents.length === 0 ? (
        <div className="empty-state">No agents configured yet</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Status</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Net profit</th>
              <th>Avg duration</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent_id}>
                <td>{a.name}</td>
                <td>
                  <span className={`pill ${a.active ? "buy" : "closed"}`}>{a.active ? "active" : "inactive"}</span>
                </td>
                <td>{a.trades_count}</td>
                <td>{a.win_rate_pct.toFixed(1)}%</td>
                <td className={a.net_profit >= 0 ? "text-green" : "text-red"}>
                  ₹{a.net_profit.toLocaleString("en-IN")}
                </td>
                <td>{a.avg_duration_hours != null ? `${a.avg_duration_hours.toFixed(1)}h` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
