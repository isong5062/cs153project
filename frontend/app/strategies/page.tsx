"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { StrategyRow } from "@/components/ui";
import { api } from "@/lib/api";
import type { StrategyMode, StrategySpec } from "@/lib/types";

function defaultSpec(mode: StrategyMode, universe: string[]): StrategySpec {
  return {
    mode,
    universe,
    regime_rules: {
      crash: { target_exposure: 0.0, max_leverage: 1.0 },
      bear: { target_exposure: 0.25, max_leverage: 1.0 },
      neutral: { target_exposure: 0.5, max_leverage: 1.0 },
      bull: { target_exposure: 0.95, max_leverage: 1.25 },
      euphoria: { target_exposure: 0.6, max_leverage: 1.0 },
    },
    params: {},
    risk_overrides: { max_risk_per_trade: 0.01 },
  };
}

export default function StrategiesPage() {
  const qc = useQueryClient();
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });

  const [name, setName] = useState("");
  const [mode, setMode] = useState<StrategyMode>("manual");
  const [universe, setUniverse] = useState("AAPL, MSFT, NVDA");

  const create = useMutation({
    mutationFn: () =>
      api.createStrategy(
        name || "Untitled",
        defaultSpec(
          mode,
          universe.split(",").map((s) => s.trim()).filter(Boolean),
        ),
      ),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["strategies"] });
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Strategies</h1>

      <form
        className="space-y-3 rounded-lg border border-zinc-800 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className="text-sm font-medium">New strategy</div>
        <input
          className="w-full rounded bg-zinc-900 px-3 py-2 text-sm"
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="flex gap-3">
          <select
            className="rounded bg-zinc-900 px-3 py-2 text-sm"
            value={mode}
            onChange={(e) => setMode(e.target.value as StrategyMode)}
          >
            <option value="manual">Manual</option>
            <option value="self_learning">Self-learning</option>
          </select>
          <input
            className="flex-1 rounded bg-zinc-900 px-3 py-2 text-sm"
            placeholder="Universe (comma-separated)"
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
          />
        </div>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Create"}
        </button>
        {create.isError && <p className="text-sm text-red-400">{String(create.error)}</p>}
      </form>

      <div className="space-y-2">
        {(strategies.data ?? []).map((s) => (
          <StrategyRow key={s.id} id={s.id} name={s.name} mode={s.mode} status={s.status} />
        ))}
      </div>
    </div>
  );
}
