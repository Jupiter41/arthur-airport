export function heatColor(loadPct: number, locked: boolean): string {
  if (locked) return "#4b5563"; // gray-600
  if (loadPct <= 15) return "#065f46"; // emerald-800 (very calm)
  if (loadPct <= 35) return "#047857"; // emerald-700 (low)
  if (loadPct <= 55) return "#0d9488"; // teal-600 (moderate)
  if (loadPct <= 70) return "#d97706"; // amber-600 (busy)
  if (loadPct <= 85) return "#ea580c"; // orange-600 (high)
  if (loadPct <= 95) return "#dc2626"; // red-600 (near cap)
  return "#991b1b"; // red-800 (full)
}
