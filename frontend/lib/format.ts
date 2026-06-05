export type HealthState = "healthy" | "down";

export function classifyHealth(status: string): HealthState {
  return status === "ok" ? "healthy" : "down";
}

export function fmtPct(x: number | undefined | null, digits = 2): string {
  if (x === undefined || x === null || Number.isNaN(x)) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtNum(x: number | undefined | null, digits = 2): string {
  if (x === undefined || x === null || Number.isNaN(x)) return "–";
  return Number(x).toLocaleString(undefined, { maximumFractionDigits: digits });
}

const REGIME_COLORS: Record<string, string> = {
  crash: "text-red-500",
  bear: "text-orange-400",
  neutral: "text-zinc-300",
  bull: "text-emerald-400",
  euphoria: "text-emerald-300",
};

export function regimeColor(label: string): string {
  return REGIME_COLORS[label] ?? "text-zinc-300";
}

const STATUS_COLORS: Record<string, string> = {
  live: "bg-emerald-500/15 text-emerald-400",
  simulated: "bg-sky-500/15 text-sky-400",
  draft: "bg-zinc-500/15 text-zinc-400",
  paused: "bg-amber-500/15 text-amber-400",
  stopped: "bg-red-500/15 text-red-400",
};

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "bg-zinc-500/15 text-zinc-400";
}
