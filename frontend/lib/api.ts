import type {
  Alert,
  Performance,
  Proposal,
  Regime,
  RiskStatus,
  Settings,
  Strategy,
  StrategySpec,
  StrategyStatus,
  Trade,
  Version,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => req<{ status: string }>("/health"),
  settings: () => req<Settings>("/settings"),
  riskStatus: () => req<RiskStatus>("/risk/status"),
  resetRisk: (eventId: number) => req(`/risk/reset/${eventId}`, { method: "POST" }),

  strategies: () => req<Strategy[]>("/strategies"),
  strategy: (id: number) => req<Strategy>(`/strategies/${id}`),
  spec: (id: number) => req<StrategySpec>(`/strategies/${id}/spec`),
  createStrategy: (name: string, spec: StrategySpec) =>
    req<Strategy>("/strategies", { method: "POST", body: JSON.stringify({ name, spec }) }),
  updateSpec: (id: number, spec: StrategySpec) =>
    req<Version>(`/strategies/${id}/spec`, { method: "PUT", body: JSON.stringify({ spec }) }),
  setStatus: (id: number, status: StrategyStatus) =>
    req<Strategy>(`/strategies/${id}/status`, { method: "POST", body: JSON.stringify({ status }) }),
  promote: (id: number) => req<Strategy>(`/strategies/${id}/promote`, { method: "POST" }),
  versions: (id: number) => req<Version[]>(`/strategies/${id}/versions`),
  performance: (id: number) => req<Performance>(`/strategies/${id}/performance`),
  trades: (id: number) => req<Trade[]>(`/strategies/${id}/trades`),

  proposals: (strategyId?: number) =>
    req<Proposal[]>(`/proposals${strategyId ? `?strategy_id=${strategyId}` : ""}`),
  approveProposal: (id: number, editedSpec?: StrategySpec) =>
    req<Version>(`/proposals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ edited_spec: editedSpec ?? null }),
    }),
  rejectProposal: (id: number) => req<Proposal>(`/proposals/${id}/reject`, { method: "POST" }),

  currentRegime: (symbol = "SPY") => req<Regime | null>(`/regimes/current?symbol=${symbol}`),

  alerts: (level?: string) => req<Alert[]>(`/alerts${level ? `?level=${level}` : ""}`),
};
