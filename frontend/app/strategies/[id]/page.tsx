"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Card, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtNum, fmtPct } from "@/lib/format";
import type { StrategySpec, StrategyStatus } from "@/lib/types";

const STATUSES: StrategyStatus[] = ["simulated", "paused", "stopped"];

export default function StrategyDetail() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const qc = useQueryClient();
  const enabled = Number.isFinite(id);

  const strategy = useQuery({ queryKey: ["strategy", id], queryFn: () => api.strategy(id), enabled });
  const spec = useQuery({ queryKey: ["spec", id], queryFn: () => api.spec(id), enabled });
  const versions = useQuery({ queryKey: ["versions", id], queryFn: () => api.versions(id), enabled });
  const perf = useQuery({ queryKey: ["perf", id], queryFn: () => api.performance(id), enabled });
  const trades = useQuery({ queryKey: ["trades", id], queryFn: () => api.trades(id), enabled });

  const [draft, setDraft] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (spec.data) setDraft(JSON.stringify(spec.data, null, 2));
  }, [spec.data]);

  const save = useMutation({
    mutationFn: () => {
      let parsed: StrategySpec;
      try {
        parsed = JSON.parse(draft);
      } catch {
        throw new Error("Invalid JSON");
      }
      return api.updateSpec(id, parsed);
    },
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["spec", id] });
      qc.invalidateQueries({ queryKey: ["versions", id] });
    },
    onError: (e) => setErr(String(e)),
  });

  const promote = useMutation({
    mutationFn: () => api.promote(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy", id] }),
  });
  const setStatus = useMutation({
    mutationFn: (st: StrategyStatus) => api.setStatus(id, st),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy", id] }),
  });

  const s = strategy.data;
  if (!s) return <p className="text-zinc-500">Loading…</p>;
  const m = perf.data?.metrics ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{s.name}</h1>
          <div className="text-sm text-zinc-500">{s.mode}</div>
        </div>
        <StatusBadge status={s.status} />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => promote.mutate()}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm hover:bg-emerald-500"
        >
          Promote to live
        </button>
        {STATUSES.map((st) => (
          <button
            key={st}
            onClick={() => setStatus.mutate(st)}
            className="rounded bg-zinc-800 px-3 py-1.5 text-sm hover:bg-zinc-700"
          >
            Set {st}
          </button>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Performance">
          <Stat label="Total return" value={fmtPct(m.total_return)} />
          <Stat label="Sharpe" value={fmtNum(m.sharpe)} />
          <Stat label="Max drawdown" value={fmtPct(m.max_drawdown)} />
          <Stat label="Win rate" value={fmtPct(m.win_rate)} />
        </Card>
        <Card title="Versions">
          <div className="space-y-1 text-sm">
            {(versions.data ?? []).map((v) => (
              <div key={v.id} className="flex justify-between border-b border-zinc-800 py-1">
                <span>v{v.version_num}</span>
                <span className="text-zinc-500">{v.created_by}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Spec (your edits apply immediately)">
        <textarea
          className="h-72 w-full rounded bg-zinc-950 p-3 font-mono text-xs"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="rounded bg-sky-600 px-4 py-1.5 text-sm hover:bg-sky-500 disabled:opacity-50"
          >
            Save spec
          </button>
          {err && <span className="text-sm text-red-400">{err}</span>}
        </div>
      </Card>

      <Card title="Recent trades">
        {(trades.data ?? []).length === 0 ? (
          <p className="text-sm text-zinc-500">No trades yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500">
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(trades.data ?? []).map((t) => (
                <tr key={t.id} className="border-t border-zinc-800">
                  <td>{t.symbol}</td>
                  <td>{t.side}</td>
                  <td>{fmtNum(t.qty)}</td>
                  <td>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
