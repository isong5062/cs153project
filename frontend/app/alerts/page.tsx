"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Alert } from "@/lib/types";

const LEVEL_STYLE: Record<string, string> = {
  info: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  critical: "border-red-500/30 bg-red-500/10 text-red-300",
};

export default function AlertsPage() {
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.alerts(),
    refetchInterval: 15000,
  });
  const items: Alert[] = alerts.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Alerts</h1>
      <p className="text-sm text-zinc-500">
        Operational events: circuit-breaker trips, worker errors, and pending proposals.
      </p>

      {items.length === 0 && <p className="text-sm text-zinc-500">No alerts.</p>}

      {items.map((a) => (
        <div
          key={a.id}
          className={`flex items-start justify-between rounded-lg border p-4 ${
            LEVEL_STYLE[a.level] ?? "border-zinc-800"
          }`}
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs">
              <span className="rounded bg-black/20 px-2 py-0.5 uppercase">{a.level}</span>
              <span className="text-zinc-400">{a.category}</span>
            </div>
            <p className="text-sm text-zinc-100">{a.message}</p>
          </div>
          <time className="shrink-0 pl-4 text-xs text-zinc-500">
            {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
          </time>
        </div>
      ))}
    </div>
  );
}
