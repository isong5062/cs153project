"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: () => api.proposals() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["proposals"] });
  const approve = useMutation({ mutationFn: (id: number) => api.approveProposal(id), onSuccess: invalidate });
  const reject = useMutation({ mutationFn: (id: number) => api.rejectProposal(id), onSuccess: invalidate });

  const items = proposals.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Approvals</h1>
      <p className="text-sm text-zinc-500">
        App-generated proposals. Nothing is applied until you approve.
      </p>

      {items.length === 0 && <p className="text-sm text-zinc-500">No pending proposals.</p>}

      {items.map((p) => (
        <div key={p.id} className="space-y-2 rounded-lg border border-zinc-800 p-4">
          <div className="flex items-center justify-between">
            <div className="text-sm text-zinc-400">
              <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs uppercase">{p.source}</span>
              {" · "}strategy #{p.strategy_id}
              {" · "}backtest #{p.backtest_id ?? "–"}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => approve.mutate(p.id)}
                className="rounded bg-emerald-600 px-3 py-1 text-xs hover:bg-emerald-500"
              >
                Approve
              </button>
              <button
                onClick={() => reject.mutate(p.id)}
                className="rounded bg-red-600/80 px-3 py-1 text-xs hover:bg-red-600"
              >
                Reject
              </button>
            </div>
          </div>
          <p className="text-sm text-zinc-300">{p.rationale}</p>
        </div>
      ))}
    </div>
  );
}
