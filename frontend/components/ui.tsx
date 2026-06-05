import Link from "next/link";

import { statusColor } from "@/lib/format";

export function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      {title && <div className="mb-1 text-xs uppercase tracking-wide text-zinc-500">{title}</div>}
      <div>{children}</div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor(status)}`}>
      {status}
    </span>
  );
}

export function StrategyRow({
  id,
  name,
  mode,
  status,
}: {
  id: number;
  name: string;
  mode: string;
  status: string;
}) {
  return (
    <Link
      href={`/strategies/${id}`}
      className="flex items-center justify-between rounded border border-zinc-800 px-4 py-3 hover:bg-zinc-900"
    >
      <div>
        <div className="font-medium">{name}</div>
        <div className="text-xs text-zinc-500">{mode}</div>
      </div>
      <StatusBadge status={status} />
    </Link>
  );
}

export function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b border-zinc-800 py-1 text-sm">
      <span className="text-zinc-400">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
