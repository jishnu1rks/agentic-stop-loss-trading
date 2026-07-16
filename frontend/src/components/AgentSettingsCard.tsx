import { useState } from "react";
import { api } from "../api/client";
import type { Agent, AgentRiskConfig, AgentScheduleConfig } from "../api/types";

export default function AgentSettingsCard({ agent, onSaved }: { agent: Agent; onSaved: () => void }) {
  const [active, setActive] = useState(agent.active);
  const [risk, setRisk] = useState<AgentRiskConfig>(agent.config.risk);
  const [schedule, setSchedule] = useState<AgentScheduleConfig>(agent.config.schedule);
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
    if (risk.buy_stop_loss_pct < PCT_MIN || risk.buy_stop_loss_pct > PCT_MAX) {
      return `Buy stop-loss % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.sell_stop_loss_pct < PCT_MIN || risk.sell_stop_loss_pct > PCT_MAX) {
      return `Sell stop-loss % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.target_pct != null && (risk.target_pct < PCT_MIN || risk.target_pct > PCT_MAX)) {
      return `Target % must be between ${PCT_MIN}% and ${PCT_MAX}%.`;
    }
    if (risk.position_size_value <= 0) {
      return risk.position_size_type === "fixed_amount" ? "Amount per trade must be positive." : "% per trade must be positive.";
    }
    if (risk.position_size_type === "fixed_amount" && risk.position_size_value > risk.max_daily_capital) {
      return "Amount per trade can't exceed max daily capital.";
    }
    if (risk.position_size_type === "pct_capital" && risk.position_size_value > 100) {
      return "% per trade can't exceed 100%.";
    }
    if (risk.max_daily_capital <= 0) {
      return "Max daily capital must be positive.";
    }
    if (risk.max_concurrent_positions < 1) {
      return "Max concurrent positions must be at least 1.";
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
        active,
        universe: agent.config.universe,
        strategy: agent.strategy,
        strategy_params: agent.config.strategy_params,
        risk,
        schedule,
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

  const universeSummary =
    agent.config.universe.type === "watchlist"
      ? `Watchlist: ${(agent.config.universe.value as string[]).join(", ")}`
      : `Index: ${agent.config.universe.value}`;

  return (
    <div className="panel" style={{ marginBottom: 20 }}>
      <div className="panel-header">
        <div>
          <strong>{agent.name}</strong>
          <div className="text-dim" style={{ fontSize: 12, marginTop: 2 }}>
            {agent.agent_id} · {agent.strategy} · {universeSummary}
          </div>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active
        </label>
      </div>

      {error && <div className="error-banner">{error}</div>}

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
        <div className="form-field">
          <label>Position sizing</label>
          <select
            value={risk.position_size_type}
            onChange={(e) => setRiskField("position_size_type", e.target.value as AgentRiskConfig["position_size_type"])}
          >
            <option value="fixed_amount">Fixed amount</option>
            <option value="pct_capital">% of daily capital</option>
          </select>
        </div>
        <div className="form-field">
          <label>{risk.position_size_type === "fixed_amount" ? "Amount per trade" : "% per trade"}</label>
          <input
            type="number"
            min={0}
            value={risk.position_size_value}
            onChange={(e) => setRiskField("position_size_value", Number(e.target.value))}
          />
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
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, paddingBottom: 8 }}>
          <input
            type="checkbox"
            checked={schedule.market_hours_only}
            onChange={(e) => setSchedule((prev) => ({ ...prev, market_hours_only: e.target.checked }))}
          />
          Market hours only
        </label>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn btn-buy" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        {savedAt && Date.now() - savedAt < 4000 && <span className="text-green" style={{ fontSize: 12 }}>Saved</span>}
      </div>
    </div>
  );
}
