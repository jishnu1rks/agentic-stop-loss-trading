import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent, AgentBreakdown } from "../api/types";
import AgentSettingsCard from "../components/AgentSettingsCard";
import AgentStatusLegend from "../components/AgentStatusLegend";
import AgentTable from "../components/AgentTable";

// Recommendation agents (llm_recommendation) only ever suggest ideas - they
// read most naturally as the "front page" of this list, ahead of agents that
// actually place trades.
function byRecommendationFirst(a: Agent, b: Agent): number {
  const rank = (agent: Agent) => (agent.strategy === "llm_recommendation" ? 0 : 1);
  return rank(a) - rank(b);
}

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
      {/* <div className="section">
        <AgentTable agents={breakdown} />
      </div> */}

      <div className="section">
        <AgentStatusLegend />
      </div>

      <div className="section">
        {agents.length === 0 ? (
          <div className="panel">
            <div className="empty-state">No agents configured yet</div>
          </div>
        ) : (
          <div className="agent-grid">
            {[...agents]
              .sort(byRecommendationFirst)
              .map((a) => (
                <AgentSettingsCard
                  key={a.agent_id}
                  agent={a}
                  onSaved={() => {
                    load();
                    onChanged();
                  }}
                />
              ))}
          </div>
        )}
      </div>
    </>
  );
}
