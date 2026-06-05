"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, StrategyRow } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtPct, regimeColor } from "@/lib/format";

export default function Dashboard() {
  const regime = useQuery({ queryKey: ["regime"], queryFn: () => api.currentRegime() });
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const risk = useQuery({ queryKey: ["risk"], queryFn: api.riskStatus });

  const r = regime.data;
  const list = strategies.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card title="Market Regime (SPY)">
          {r ? (
            <div>
              <span className={`text-2xl font-semibold ${regimeColor(r.label)}`}>{r.label}</span>
              <div className="text-sm text-zinc-400">
                confidence {fmtPct(r.confidence)}
                {r.unstable ? " · unstable" : ""}
              </div>
            </div>
          ) : (
            <span className="text-zinc-500">No regime yet — train a model</span>
          )}
        </Card>
        <Card title="Strategies">
          <span className="text-2xl font-semibold">{strategies.data?.length ?? "–"}</span>
        </Card>
        <Card title="Risk">
          {risk.data?.blocked ? (
            <span className="text-xl font-semibold text-red-400">BLOCKED</span>
          ) : (
            <span className="text-xl font-semibold text-emerald-400">OK</span>
          )}
        </Card>
      </div>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Strategies</h2>
        {list.length === 0 ? (
          <p className="text-sm text-zinc-500">No strategies yet — create one under Strategies.</p>
        ) : (
          <div className="space-y-2">
            {list.map((s) => (
              <StrategyRow key={s.id} id={s.id} name={s.name} mode={s.mode} status={s.status} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
