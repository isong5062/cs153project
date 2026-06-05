export type StrategyMode = "manual" | "self_learning";
export type StrategyStatus = "draft" | "simulated" | "live" | "paused" | "stopped";

export interface RegimeRule {
  target_exposure: number;
  max_leverage: number;
  entry?: { logic: string; conditions: unknown[] };
  exit?: { logic: string; conditions: unknown[] };
}

export interface StrategySpec {
  mode: StrategyMode;
  universe: string[];
  regime_rules: Record<string, RegimeRule>;
  indicators?: unknown[];
  params?: Record<string, number>;
  risk_overrides?: { max_risk_per_trade: number };
}

export interface Strategy {
  id: number;
  name: string;
  mode: StrategyMode;
  status: StrategyStatus;
  current_version_id: number | null;
  created_at: string;
}

export interface Version {
  id: number;
  version_num: number;
  created_by: string;
  created_at: string;
}

export interface Proposal {
  id: number;
  strategy_id: number;
  source: string;
  status: string;
  rationale: string;
  backtest_id: number | null;
  created_at: string;
}

export interface Regime {
  symbol: string;
  ts: string;
  label: string;
  confidence: number;
  unstable: boolean;
}

export interface Performance {
  equity_curve: { ts: string; equity: number }[];
  metrics: Record<string, number>;
}

export interface Trade {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  status: string;
  executor: string;
  created_at: string;
}

export interface Settings {
  regime_symbol: string;
  default_universe: string[];
  bar_timeframe: string;
  paper_only: boolean;
  risk_limits: Record<string, number>;
  budget: { max_self_learning_strategies: number; daily_token_budget: number };
  alpaca_configured: boolean;
  anthropic_configured: boolean;
}

export interface Alert {
  id: number;
  level: "info" | "warning" | "critical";
  category: string;
  message: string;
  detail: Record<string, unknown>;
  delivered: boolean;
  created_at: string | null;
}

export interface RiskStatus {
  blocked: boolean;
  events: {
    id: number;
    type: string;
    scope: string;
    strategy_id: number | null;
    resolved: boolean;
    triggered_at: string | null;
  }[];
}
