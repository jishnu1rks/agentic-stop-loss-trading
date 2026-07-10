import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent, AgentBreakdown } from "../api/types";
import AgentSettingsCard from "../components/AgentSettingsCard";
import AgentTable from "../components/AgentTable";

export default function AgentSettingsPage({ refreshTick, onChanged }: { refreshTick: number; onChanged: () => void }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [breakdown, setBreakdown] = useState<AgentBreakdown[]>([]);

  const load = () => {
    api.listAgents().then(setAgents).catch(() => setAgents([]));
    api.agentsBreakdown().then(setBreakdown).catch(() => setBreakdown([]));
  };

  useEffect(load, [refreshTick]);

  return (
    <>
      <div className="section">
        <AgentTable agents={breakdown} />
      </div>

      <div className="section">
        {agents.length === 0 ? (
          <div className="panel">
            <div className="empty-state">No agents configured yet</div>
          </div>
        ) : (
          agents.map((a) => (
            <AgentSettingsCard
              key={a.agent_id}
              agent={a}
              onSaved={() => {
                load();
                onChanged();
              }}
            />
          ))
        )}
      </div>
    </>
  );
}
