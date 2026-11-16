export function formatRelativeTime(iso: string, simTime: string | null): string {
  const utc = (value: string) => Date.parse(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  const started = utc(iso);
  const observed = simTime ? utc(simTime) : NaN;
  if (!Number.isFinite(started) || !Number.isFinite(observed)) return "simulation age unavailable";
  const diff = Math.floor((observed - started) / 60000);
  if (diff < 0) return "start is ahead of source clock";
  if (diff < 1) return "this sim-minute";
  if (diff < 60) return `${diff} sim-min ago`;
  return `${Math.floor(diff / 60)}h ${diff % 60}m ago (simulated)`;
}

export function formatSimTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}
