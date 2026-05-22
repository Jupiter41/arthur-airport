import { useIncidentStore } from "../../stores/incidentStore";

export function CriticalBanner() {
  const incidents = useIncidentStore((s) => s.incidents);
  const critical = Object.values(incidents).find(
    (i) => i.severity === "critical" && i.status === "active",
  );
  if (!critical) return null;

  return (
    <div className="bg-red-900/80 border border-red-600 text-white px-4 py-2 text-sm font-bold animate-pulse">
      ⚠ CRITICAL: {critical.title} — {critical.location}
    </div>
  );
}
