import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Agent } from "../api/types";
import AgentSettingsCard from "../components/AgentSettingsCard";
import AgentStatusLegend from "../components/AgentStatusLegend";

const LLM_STRATEGIES = ["llm_recommendation", "llm_recommendation_execution"];

// These two notes are identical for every llm_recommendation/execution
// agent - shown once here instead of repeated on every individual card.
function LlmAgentsNote() {
  return (
    <div className="panel" style={{ marginBottom: 20 }}>
      <div className="field-hint" style={{ marginBottom: 12 }}>
        MVP limit: AI scans run at most once per hour, only between 11:00 AM-3:00 PM, to conserve API quota. Not yet
        user-editable - will be made configurable later.
      </div>
      <div className="field-hint">
        Eligibility filter: before reaching an agent (or the AI), every symbol from the live screener must clear a
        fundamentals health/valuation check - hard-disqualified outright if Debt/Equity is 3x or more, or earnings
        growth has collapsed below -50%. Otherwise it's scored on Debt/Equity, PEG, revenue/earnings growth, insider
        holding %, and P/B (whichever of these are available), and must score at least 50% to pass. A symbol with no
        fundamentals data at all is kept (treated as neutral) rather than excluded for a data gap.
      </div>
    </div>
  );
}

export default function AgentSettingsPage({ refreshTick, onChanged }: { refreshTick: number; onChanged: () => void }) {
  const [agents, setAgents] = useState<Agent[]>([]);

  const load = () => {
    api.listAgents().then(setAgents).catch(() => setAgents([]));
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
        {agents.some((a) => LLM_STRATEGIES.includes(a.strategy)) && <LlmAgentsNote />}
        {agents.length === 0 ? (
          <div className="panel">
            <div className="empty-state">No agents configured yet</div>
          </div>
        ) : (
          <>
            <div className="agent-grid">
              {agents
                .filter((a) => a.strategy === "llm_recommendation")
                .map((a) => (
                  <AgentSettingsCard
                    key={a.agent_id}
                    agent={a}
                    allAgents={agents}
                    onSaved={() => {
                      load();
                      onChanged();
                    }}
                  />
                ))}
            </div>
            <div className="agent-grid" style={{ marginTop: 16 }}>
              {agents
                .filter((a) => a.strategy !== "llm_recommendation")
                .map((a) => (
                  <AgentSettingsCard
                    key={a.agent_id}
                    agent={a}
                    allAgents={agents}
                    onSaved={() => {
                      load();
                      onChanged();
                    }}
                  />
                ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
