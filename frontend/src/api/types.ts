export type Direction = "buy" | "sell";
export type TradeStatus = "open" | "closed" | "error";
export type ExitReason = "stop_loss" | "target" | "manual" | "timeout";

export interface Trade {
  trade_id: string;
  agent_id: string | null;
  stock_symbol: string;
  direction: Direction;
  quantity: number;
  buy_price: number;
  sell_price: number | null;
  purchase_date: string;
  sell_date: string | null;
  stop_loss_pct: number;
  stop_loss_price: number;
  target_price: number | null;
  exit_reason: ExitReason | null;
  gross_profit: number | null;
  charges: number | null;
  tax: number | null;
  net_profit: number | null;
  status: TradeStatus;
  broker_order_id: string | null;
  is_manual: boolean;
}

export interface AgentRiskConfig {
  buy_stop_loss_pct: number;
  sell_stop_loss_pct: number;
  target_pct?: number | null;
  position_size_type: "fixed_amount" | "pct_capital";
  position_size_value: number;
  max_concurrent_positions: number;
  max_daily_capital: number;
}

export interface AgentScheduleConfig {
  type: "interval";
  interval_minutes: number;
  market_hours_only: boolean;
}

export interface AgentUniverseConfig {
  type: "watchlist" | "index";
  value: string[] | string;
}

export interface AgentConfig {
  agent_id: string;
  name: string;
  active: boolean;
  universe: AgentUniverseConfig;
  strategy: string;
  strategy_params: Record<string, unknown>;
  risk: AgentRiskConfig;
  schedule: AgentScheduleConfig;
}

// Same shape as AgentConfig - used when submitting an update (PUT /agents/{id}).
export type AgentConfigIn = AgentConfig;

export interface Agent {
  agent_id: string;
  name: string;
  strategy: string;
  config: AgentConfig;
  active: boolean;
  created_at: string;
}

export interface Kpis {
  total_trades_all_time: number;
  total_trades_this_month: number;
  total_quantity_traded: number;
  total_net_profit_all_time: number;
  total_net_profit_this_month: number;
  total_capital_invested_this_month: number;
  open_positions_count: number;
  total_charges_paid: number;
  total_tax_accrued: number;
  starting_capital: number;
  capital_deployed: number;
  realized_pnl: number;
  free_capital: number;
}

export interface AgentBreakdown {
  agent_id: string;
  name: string;
  active: boolean;
  trades_count: number;
  win_rate_pct: number;
  net_profit: number;
  avg_duration_hours: number | null;
}

export interface Recommendation {
  symbol: string;
  unavailable: boolean;
  reason?: string;
  direction?: Direction;
  cmp?: number;
  // watchlist_trigger fields
  entry_low?: number;
  entry_high?: number;
  in_band?: boolean;
  // momentum_breakout fields
  prior_high?: number;
  breakout_pct?: number;
  in_signal?: boolean;
  // shared
  stop_loss_price?: number;
  target_price?: number | null;
  upside_pct?: number | null;
  quantity?: number;
  proximity_pct?: number;
  already_open?: boolean;
  rationale?: string;
}

export interface ManualTradeInput {
  stock_symbol: string;
  direction: Direction;
  quantity: number;
  stop_loss_pct?: number;
  target_pct?: number;
}
