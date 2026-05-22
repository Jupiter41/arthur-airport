import { StatusBadge } from "../../components/StatusBadge";
import { formatSimTime } from "./utils";
import type { IncidentAlert } from "../../types";

export function AlertFeed({ alerts }: { alerts: IncidentAlert[] }) {
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Alert Feed
      </h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {alerts.length === 0 && (
          <div className="text-xs text-gray-400">No alerts yet</div>
        )}
        {alerts.map((a) => (
          <div
            key={a.id}
            className={`flex gap-2 text-xs py-1 ${
              a.severity === "critical"
                ? "border-l-2 border-red-500 pl-2"
                : "pl-3"
            }`}
          >
            <span className="text-gray-400 font-mono whitespace-nowrap">
              {formatSimTime(a.sim_time)}
            </span>
            <StatusBadge status={a.severity} className="text-[10px]" />
            <span className="text-gray-300">{a.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
