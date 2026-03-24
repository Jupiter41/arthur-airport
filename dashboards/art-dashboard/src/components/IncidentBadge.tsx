import { useIncidentStore } from "../stores/incidentStore";

export function IncidentBadge() {
  const incidents = useIncidentStore((s) => s.incidents);
  const active = Object.values(incidents).filter(
    (i) => i.status === "active" || i.status === "contained",
  );

  if (active.length === 0) return null;

  const hasCritical = active.some((i) => i.severity === "critical");

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded ${
        hasCritical
          ? "bg-red-600 text-white animate-pulse"
          : "bg-amber-600 text-white"
      }`}
    >
      ⚠ {active.length} incident{active.length !== 1 ? "s" : ""}
    </span>
  );
}
