import { useState } from "react";
import { api } from "../api/client";
import type { Agent, AgentRiskConfig, AgentScheduleConfig } from "../api/types";

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  llm_recommendation:
    "Tries a live screener first - 5 large-cap, 5 mid-cap, 5 small-cap trending NSE stocks, each pre-screened for financial health/valuation (see eligibility criteria below). Only if that live fetch fails does it fall back to the fixed watchlist below. Either way, it sends the resulting stocks' current price/volume snapshot to an AI model along with the trading prompt, and asks it which symbols look worth buying or selling right now.",
  llm_recommendation_execution:
    "Aggregates AI-generated buy/sell signals from every active Recommending agent (not just one), narrowed by the confidence/direction filters below - the Recommending agents only suggest, this one sizes, protects, and enters trades on the signals that pass those filters, using the risk settings below. The switch below can pause new entries entirely while leaving existing positions' monitoring/exits untouched.",
  momentum_breakout:
    "Scans its configured stocks for names breaking out on strong price momentum and above-average volume, then automatically enters a trade the moment a breakout is confirmed.",
  watchlist_trigger:
    "Watches a fixed list of symbols you've configured and enters a trade only when price crosses the specific level you've set for that symbol.",
};

function strategyDescription(strategy: string): string {
  return STRATEGY_DESCRIPTIONS[strategy] ?? "Scans its configured stocks on the schedule below and enters trades according to its configured strategy.";
}

// Mirrors MAX_TRADE_PCT_OF_DAILY_CAPITAL (backend/app/agent_runtime.py) -
// no per-trade amount to configure, but no single trade may commit more
// than this fraction of max_daily_capital either.
const MAX_TRADE_PCT_OF_DAILY_CAPITAL = 0.25;

// Only used as a throwaway initial value for recommend-only agents, which
// carry no risk config at all (see AgentConfigIn.risk backend-side) - never
// rendered or submitted for them.
const DEFAULT_RISK: AgentRiskConfig = {
  buy_stop_loss_pct: 2,
  sell_stop_loss_pct: 2,
  target_pct: null,
  max_concurrent_positions: 5,
  max_daily_capital: 50000,
};

// Directions an Execution agent will act on - "both" (default, matches the
// pre-existing unconditional behavior) or restricted to one side.
type ExecutionDirectionFilter = "both" | "buy" | "sell";

export default function AgentSettingsCard({
  agent,
  allAgents = [],
  onSaved,
}: {
  agent: Agent;
  allAgents?: Agent[];
  onSaved: () => void;
}) {
  const [risk, setRisk] = useState<AgentRiskConfig>(agent.config.risk ?? DEFAULT_RISK);
  const [schedule, setSchedule] = useState<AgentScheduleConfig>(agent.config.schedule);
  const [name, setName] = useState(agent.name);
  const [active, setActive] = useState(agent.active);
  const [togglingActive, setTogglingActive] = useState(false);
  const isLlmRecommendation = agent.strategy === "llm_recommendation";
  const isExecutionAgent = agent.strategy === "llm_recommendation_execution";
  const [prompt, setPrompt] = useState(
    isLlmRecommendation ? String(agent.config.strategy_params.prompt ?? "") : ""
  );

  // Every active Recommending agent this Execution agent mirrors (see
  // backend's _find_recommend_only_agents) - looked up client-side from the
  // already-fetched agent list purely for transparency (showing which
  // agents this one is actually acting on), not for saving. Aggregates all
  // of them, not just one - inactive Recommending agents are excluded.
  const sourceAgents = isExecutionAgent
    ? allAgents.filter((a) => a.strategy === "llm_recommendation" && a.active)
    : [];

  const [fallbackWatchlist, setFallbackWatchlist] = useState(() =>
    isLlmRecommendation ? (agent.config.universe.screener?.fallback_watchlist ?? []).join(", ") : ""
  );

  const [minConfidencePct, setMinConfidencePct] = useState(() =>
    isExecutionAgent ? Number(agent.config.strategy_params.min_confidence_pct ?? 0) : 0
  );
  const [directionFilter, setDirectionFilter] = useState<ExecutionDirectionFilter>(() =>
    isExecutionAgent ? ((agent.config.strategy_params.directions as ExecutionDirectionFilter) ?? "both") : "both"
  );
  // Separate from the Active/Paused switch above (which stops this agent's
  // scans entirely, including monitoring): pausing new trades only blocks
  // fresh entries - existing open positions keep getting watched and their
  // stop-loss/target GTTs still fire normally (see run_agent_scan).
  const [pauseNewTrades, setPauseNewTrades] = useState(() =>
    isExecutionAgent ? Boolean(agent.config.strategy_params.pause_new_trades) : false
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const setRiskField = <K extends keyof AgentRiskConfig>(key: K, value: AgentRiskConfig[K]) =>
    setRisk((prev) => ({ ...prev, [key]: value }));

  // Takes effect immediately (not gated behind Save changes) - a switch is
  // expected to act like a switch. Pausing an agent stops its scheduled
  // scans (see app.scheduler.schedule_agent) until switched back on.
  const toggleActive = async () => {
    const next = !active;
    setTogglingActive(true);
    try {
      await api.setAgentActive(agent.agent_id, next);
      setActive(next);
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "Failed to update active state");
    } finally {
      setTogglingActive(false);
    }
  };

  // Stop-loss/target are always % of entry price (CMP at fill time), never
  // a currency amount - 0.1-5% keeps a fat-fingered config from arming a
  // trade with, say, a 50% stop-loss. Mirrors the backend's AgentRiskConfig
  // bounds so a rejected save doesn't need a round-trip to explain why.
  const PCT_MIN = 0.1;
  const PCT_MAX = 5;

  const validate = (): string | null => {
    if (!name.trim()) {
      return "Agent name is required.";
    }
    if (isLlmRecommendation) {
      return !prompt.trim() ? "Prompt is required for a recommendation agent." : null;
    }
    if (risk.buy_stop_loss_pct < PCT_MIN || risk.buy_stop_loss_pct > PCT_MAX) {
      return `Buy stop-loss % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.sell_stop_loss_pct < PCT_MIN || risk.sell_stop_loss_pct > PCT_MAX) {
      return `Sell stop-loss % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.target_pct != null && (risk.target_pct < PCT_MIN || risk.target_pct > PCT_MAX)) {
      return `Target % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.max_daily_capital <= 0) {
      return "Max daily capital must be positive.";
    }
    if (risk.max_concurrent_positions < 1) {
      return "Max concurrent positions must be at least 1.";
    }
    if (isExecutionAgent && (minConfidencePct < 0 || minConfidencePct > 100)) {
      return "Minimum confidence must be between 0% and 100%.";
    }
    return null;
  };

  const save = async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateAgent(agent.agent_id, {
        agent_id: agent.agent_id,
        name: name.trim(),
        active,
        universe: isLlmRecommendation
          ? {
              type: "screener",
              value: null,
              screener: {
                sort_by: agent.config.universe.screener?.sort_by ?? "dayvolume",
                limit: agent.config.universe.screener?.limit ?? 15,
                min_market_cap: agent.config.universe.screener?.min_market_cap ?? 5_000_000_000,
                fallback_watchlist: fallbackWatchlist
                  .split(",")
                  .map((s) => s.trim().toUpperCase())
                  .filter(Boolean),
              },
            }
          : agent.config.universe,
        strategy: agent.strategy,
        strategy_params: isLlmRecommendation
          ? { ...agent.config.strategy_params, prompt }
          : isExecutionAgent
            ? {
                ...agent.config.strategy_params,
                min_confidence_pct: minConfidencePct,
                directions: directionFilter,
                pause_new_trades: pauseNewTrades,
              }
            : agent.config.strategy_params,
        risk: isLlmRecommendation ? null : risk,
        schedule: { ...schedule, market_hours_only: true },
      });
      setSavedAt(Date.now());
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "Failed to save agent settings");
    } finally {
      setSaving(false);
    }
  };



  return (
    <div className="panel" style={{ marginBottom: 20 }}>
      <div className="panel-header">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{
            background: "transparent",
            border: "none",
            font: "inherit",
            fontWeight: 700,
            fontSize: 16,
            color: "var(--text)",
            padding: 0,
            minWidth: 0,
            flex: 1,
          }}
        />
        <label className="agent-active-switch" title={active ? "Agent is active - click to pause" : "Agent is paused - click to resume"}>
          <input type="checkbox" checked={active} disabled={togglingActive} onChange={toggleActive} />
          <span className="switch-track">
            <span className="switch-thumb" />
          </span>
          {active ? "Active" : "Paused"}
        </label>
      </div>

      <div className="agent-description">{strategyDescription(agent.strategy)}</div>

      {error && <div className="error-banner">{error}</div>}

      {isLlmRecommendation && (
        <div className="form-field" style={{ marginBottom: 16 }}>
          <label>Trading prompt</label>
          <textarea
            rows={5}
            style={{ width: "100%", fontFamily: "inherit" }}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the entry criteria this agent should look for, e.g. 'Buy NSE large-caps that dropped more than 3% today on above-average volume with no negative news.'"
          />
          <span className="field-hint">
            Sent to the model alongside a live price/volume snapshot of the live-screened stocks below (or the
            fallback watchlist, if the live screener fails) - subject to the once-per-hour/11:00-15:00 limit above.
          </span>
        </div>
      )}

      {isLlmRecommendation && (
        <div className="form-field" style={{ marginBottom: 16 }}>
          <label>Fallback watchlist</label>
          <input
            type="text"
            style={{ width: "100%" }}
            value={fallbackWatchlist}
            onChange={(e) => setFallbackWatchlist(e.target.value)}
            placeholder="e.g. RELIANCE, TCS, INFY"
          />
          <span className="field-hint">
            Comma-separated symbols used only if the live screener fails - not the primary source, a safety net.
            Leave blank for no fallback (a screener failure then pauses this agent's scan instead).
          </span>
        </div>
      )}

      {isExecutionAgent && (
        <div className="form-field" style={{ marginBottom: 16 }}>
          <label>Recommending agents this agent is mirroring</label>
          {sourceAgents.length === 0 ? (
            <div className="field-hint">
              No active Recommending agent right now - this agent won't produce any signals until one is active.
            </div>
          ) : (
            <div className="field-hint">
              {sourceAgents.map((a) => a.name).join(", ")} - edit each one's own prompt on its own card above; an
              inactive Recommending agent is automatically excluded here.
            </div>
          )}
        </div>
      )}

      {isExecutionAgent && (
        <div className="form-field" style={{ marginBottom: 16 }}>
          <label className="agent-active-switch" title="Blocks only new entries - existing open positions keep being monitored and exit normally">
            <input
              type="checkbox"
              checked={pauseNewTrades}
              onChange={(e) => setPauseNewTrades(e.target.checked)}
            />
            <span className="switch-track">
              <span className="switch-thumb" />
            </span>
            {pauseNewTrades ? "New trades paused" : "New trades enabled"}
          </label>
          <span className="field-hint">
            Stops this agent from opening any new position - open positions are still watched and their stop-loss/
            target still fire normally. Takes effect on Save changes.
          </span>
        </div>
      )}

      {isExecutionAgent && (
        <div className="manual-trade-form" style={{ marginBottom: 16 }}>
          <div className="form-field">
            <label>Minimum confidence to auto-enter</label>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={minConfidencePct}
              onChange={(e) => setMinConfidencePct(Number(e.target.value))}
            />
            <span className="field-hint">0% = act on every mirrored signal regardless of AI confidence</span>
          </div>
          <div className="form-field">
            <label>Directions to act on</label>
            <select
              value={directionFilter}
              onChange={(e) => setDirectionFilter(e.target.value as ExecutionDirectionFilter)}
            >
              <option value="both">Buy and sell signals</option>
              <option value="buy">Buy signals only</option>
              <option value="sell">Sell signals only</option>
            </select>
          </div>
        </div>
      )}

      {!isLlmRecommendation && (
        <>
          <div className="manual-trade-form" style={{ marginBottom: 16 }}>
            <div className="form-field">
              <label>Buy stop-loss %</label>
              <input
                type="number"
                min={PCT_MIN}
                max={PCT_MAX}
                step={0.1}
                value={risk.buy_stop_loss_pct}
                onChange={(e) => setRiskField("buy_stop_loss_pct", Number(e.target.value))}
              />
              <span className="field-hint">{PCT_MIN}% - {PCT_MAX}%</span>
            </div>
            <div className="form-field">
              <label>Sell stop-loss %</label>
              <input
                type="number"
                min={PCT_MIN}
                max={PCT_MAX}
                step={0.1}
                value={risk.sell_stop_loss_pct}
                onChange={(e) => setRiskField("sell_stop_loss_pct", Number(e.target.value))}
              />
              <span className="field-hint">{PCT_MIN}% - {PCT_MAX}%</span>
            </div>
            <div className="form-field">
              <label>Target %</label>
              <input
                type="number"
                min={PCT_MIN}
                max={PCT_MAX}
                step={0.1}
                value={risk.target_pct ?? ""}
                onChange={(e) => setRiskField("target_pct", e.target.value === "" ? null : Number(e.target.value))}
              />
              <span className="field-hint">{PCT_MIN}% - {PCT_MAX}%</span>
            </div>
          </div>

          <div className="manual-trade-form" style={{ marginBottom: 16 }}>
            <div className="form-field">
              <label>Max concurrent positions</label>
              <input
                type="number"
                min={1}
                value={risk.max_concurrent_positions}
                onChange={(e) => setRiskField("max_concurrent_positions", Number(e.target.value))}
              />
            </div>
            <div className="form-field">
              <label>Max daily capital</label>
              <input
                type="number"
                min={0}
                value={risk.max_daily_capital}
                onChange={(e) => setRiskField("max_daily_capital", Number(e.target.value))}
              />
              <span className="field-hint">
                Each trade uses whatever's available, capped at {MAX_TRADE_PCT_OF_DAILY_CAPITAL * 100}% of this per
                trade (≈{Math.round(risk.max_daily_capital * MAX_TRADE_PCT_OF_DAILY_CAPITAL).toLocaleString("en-IN")})
              </span>
            </div>
            <div className="form-field">
              <label>Scan interval (minutes)</label>
              <input
                type="number"
                min={1}
                value={schedule.interval_minutes}
                onChange={(e) => setSchedule((prev) => ({ ...prev, interval_minutes: Number(e.target.value) }))}
              />
            </div>
          </div>
        </>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn btn-buy" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        {savedAt && Date.now() - savedAt < 4000 && <span className="text-green" style={{ fontSize: 12 }}>Saved</span>}
      </div>
    </div>
  );
}
