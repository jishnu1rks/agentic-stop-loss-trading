import { useState } from "react";
import { api } from "../api/client";
import type { Agent, AgentRiskConfig, AgentScheduleConfig } from "../api/types";

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  llm_recommendation:
    "Pulls a live universe of trending NSE stocks (5 large-cap, 5 mid-cap, 5 small-cap, each pre-screened for financial health/valuation - see eligibility criteria below), sends their current price/volume snapshot to an AI model along with the trading prompt below, and asks it which symbols look worth buying or selling right now.",
  llm_recommendation_execution:
    "Mirrors the Recommending agent's AI-generated buy/sell signals (same prompt, same stocks), narrowed by the confidence/direction filters below - the Recommending agent only suggests, this one sizes, protects, and enters trades on the signals that pass those filters, using the risk settings below.",
  momentum_breakout:
    "Scans its configured stocks for names breaking out on strong price momentum and above-average volume, then automatically enters a trade the moment a breakout is confirmed.",
  watchlist_trigger:
    "Watches a fixed list of symbols you've configured and enters a trade only when price crosses the specific level you've set for that symbol.",
};

// The fundamentals health/valuation screen every screener-sourced universe
// symbol must clear before an agent (or the AI) ever sees it - see backend
// app/fundamentals.py:is_recommendable, applied in agent_runtime.filter_recommendable.
const ELIGIBILITY_CRITERIA_NOTE =
  "Eligibility filter: before reaching this agent (or the AI), every symbol from the live screener must clear a " +
  "fundamentals health/valuation check - hard-disqualified outright if Debt/Equity is 3x or more, or earnings " +
  "growth has collapsed below -50%. Otherwise it's scored on Debt/Equity, PEG, revenue/earnings growth, insider " +
  "holding %, and P/B (whichever of these are available), and must score at least 50% to pass. A symbol with no " +
  "fundamentals data at all is kept (treated as neutral) rather than excluded for a data gap.";

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
  const isLlmRecommendation = agent.strategy === "llm_recommendation";
  const isExecutionAgent = agent.strategy === "llm_recommendation_execution";
  const [prompt, setPrompt] = useState(
    isLlmRecommendation ? String(agent.config.strategy_params.prompt ?? "") : ""
  );

  // The Recommending agent this Execution agent mirrors (see backend's
  // _find_recommend_only_agent) - looked up client-side from the already-
  // fetched agent list purely for transparency (showing the user what
  // prompt/universe this agent is actually acting on), not for saving.
  const sourceAgent = isExecutionAgent
    ? allAgents.find((a) => a.strategy === "llm_recommendation" && a.active && a.config.risk == null)
    : undefined;

  const [minConfidencePct, setMinConfidencePct] = useState(() =>
    isExecutionAgent ? Number(agent.config.strategy_params.min_confidence_pct ?? 0) : 0
  );
  const [directionFilter, setDirectionFilter] = useState<ExecutionDirectionFilter>(() =>
    isExecutionAgent ? ((agent.config.strategy_params.directions as ExecutionDirectionFilter) ?? "both") : "both"
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const setRiskField = <K extends keyof AgentRiskConfig>(key: K, value: AgentRiskConfig[K]) =>
    setRisk((prev) => ({ ...prev, [key]: value }));

  // Stop-loss/target are always % of entry price (CMP at fill time), never
  // a currency amount - 0.1-5% keeps a fat-fingered config from arming a
  // trade with, say, a 50% stop-loss. Mirrors the backend's AgentRiskConfig
  // bounds so a rejected save doesn't need a round-trip to explain why.
  const PCT_MIN = 0.1;
  const PCT_MAX = 5;

  const validate = (): string | null => {
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
        name: agent.name,
        // Agents are always active - trading happens on its own schedule
        // during market hours, with no manual on/off switch in this UI.
        active: true,
        universe: agent.config.universe,
        strategy: agent.strategy,
        strategy_params: isLlmRecommendation
          ? { ...agent.config.strategy_params, prompt }
          : isExecutionAgent
            ? { ...agent.config.strategy_params, min_confidence_pct: minConfidencePct, directions: directionFilter }
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
        <div>
          <strong>{agent.name}</strong>
          {/* <div className="text-dim" style={{ fontSize: 12, marginTop: 2 }}>
            {agent.agent_id} · {agent.strategy} · {universeSummary}
          </div> */}
        </div>
      </div>

      <div className="agent-description">{strategyDescription(agent.strategy)}</div>

      {(isLlmRecommendation || isExecutionAgent) && (
        <div className="field-hint" style={{ marginBottom: 12 }}>
          MVP limit: AI scans run at most once per hour, only between 11:00 AM-3:00 PM, to conserve API quota. Not
          yet user-editable - will be made configurable later.
        </div>
      )}

      {(isLlmRecommendation || isExecutionAgent) && (
        <div className="field-hint" style={{ marginBottom: 12 }}>
          {ELIGIBILITY_CRITERIA_NOTE}
        </div>
      )}

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
            Sent to the model on every scan alongside a live price/volume snapshot of this agent's configured stocks.
          </span>
        </div>
      )}

      {isExecutionAgent && (
        <div className="form-field" style={{ marginBottom: 16 }}>
          <label>Prompt this agent is acting on</label>
          <textarea
            rows={4}
            readOnly
            style={{ width: "100%", fontFamily: "inherit", opacity: 0.75 }}
            value={
              sourceAgent
                ? String(sourceAgent.config.strategy_params.prompt ?? "")
                : "No active Recommending agent found to mirror - this agent won't produce any signals."
            }
          />
          <span className="field-hint">
            Mirrored exactly from the Recommending agent ({sourceAgent?.name ?? "none configured"}) - edit it there,
            not here.
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
