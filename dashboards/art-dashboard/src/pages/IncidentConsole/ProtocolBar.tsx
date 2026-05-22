import type { Incident } from "../../types";

export function ProtocolBar({ incident }: { incident: Incident | null }) {
  if (!incident || (incident.protocols ?? []).length === 0) return null;

  return (
    <div className="flex gap-2 flex-wrap">
      {(incident.protocols ?? []).map((p) => (
        <div key={p} className="bg-gray-700 rounded px-3 py-1.5 text-xs">
          <span className="text-amber-400 mr-1">●</span>
          <span className="text-white font-medium">{p}</span>
        </div>
      ))}
    </div>
  );
}
