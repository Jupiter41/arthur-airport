import { StatusBadge } from "../../components/StatusBadge";
import { SEVERITY_BORDER, SEVERITY_BG } from "./constants";
import { formatRelativeTime } from "./utils";
import type { Incident } from "../../types";

export function IncidentCard({
  incident,
  selected,
  onSelect,
}: {
  incident: Incident;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      className={`border-l-4 ${SEVERITY_BORDER[incident.severity]} ${SEVERITY_BG[incident.severity]} 
        rounded p-3 cursor-pointer transition-all hover:ring-1 hover:ring-white/20
        ${selected ? "ring-2 ring-blue-400" : ""}
        ${incident.severity === "critical" && incident.status === "active" ? "animate-pulse" : ""}`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between mb-1">
        <StatusBadge status={incident.severity} />
        <StatusBadge status={incident.status} />
      </div>
      <div className="text-sm font-bold text-white">{incident.title}</div>
      <div className="text-xs text-gray-400 mt-1">
        {incident.location} · {formatRelativeTime(incident.started_at)}
      </div>
      {(incident.protocols ?? []).length > 0 && (
        <div className="flex gap-1 mt-2">
          {(incident.protocols ?? []).map((p) => (
            <span
              key={p}
              className="text-[10px] bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded"
            >
              {p}
            </span>
          ))}
        </div>
      )}
      <div className="text-[10px] text-gray-400 mt-1">
        ↓ {incident.cascade_depth} cascade
        {incident.cascade_depth !== 1 ? "s" : ""}
        {incident.ttr_remaining_min != null && incident.status === "active" && (
          <span className="ml-2 text-amber-400">
            ⏱ {incident.ttr_remaining_min} min left
          </span>
        )}
      </div>
    </div>
  );
}
