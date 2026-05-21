export function formatEur(v: unknown): string {
  const n = Number(v ?? 0);
  if (Number.isNaN(n)) return "€0";
  if (Math.abs(n) >= 1_000_000) return `€${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `€${(n / 1_000).toFixed(1)}K`;
  return `€${n.toFixed(0)}`;
}
