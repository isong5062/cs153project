"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, Stat } from "@/components/ui";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const s = settings.data;
  if (!s) return <p className="text-zinc-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="General">
          <Stat label="Regime symbol" value={s.regime_symbol} />
          <Stat label="Bar timeframe" value={s.bar_timeframe} />
          <Stat label="Paper only" value={String(s.paper_only)} />
          <Stat label="Alpaca configured" value={String(s.alpaca_configured)} />
          <Stat label="Anthropic configured" value={String(s.anthropic_configured)} />
        </Card>
        <Card title="Risk limits">
          {Object.entries(s.risk_limits).map(([k, v]) => (
            <Stat key={k} label={k} value={String(v)} />
          ))}
        </Card>
        <Card title="Learning budget">
          <Stat label="Max self-learning strategies" value={s.budget.max_self_learning_strategies} />
          <Stat label="Daily token budget" value={s.budget.daily_token_budget} />
        </Card>
        <Card title="Default universe">
          <div className="text-sm">{s.default_universe.join(", ")}</div>
        </Card>
      </div>
    </div>
  );
}
