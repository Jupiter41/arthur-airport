import { StatusBadge } from "../../components/StatusBadge";
import { SEVERITY_BORDER, SEVERITY_BG } from "./constants";
import type { CascadeNode, Incident } from "../../types";

export function CascadeTree({
  node,
  depth = 0,
}: {
  node: CascadeNode;
  depth?: number;
}) {
  const bgColor =
    node.status === "resolved"
      ? "bg-green-900/30 border-green-600"
      : SEVERITY_BORDER[node.severity] + " " + SEVERITY_BG[node.severity];

  return (
    <div className="ml-4" style={{ marginLeft: depth === 0 ? 0 : 16 }}>
      <div className={`border-l-2 ${bgColor} rounded p-2 mb-2`}>
        <div className="flex items-center gap-2">
          <StatusBadge status={node.severity} />
          <span className="text-sm text-white font-medium">{node.type}</span>
        </div>
        <div className="text-xs text-gray-400 mt-1">{node.description}</div>
        {node.affected_count > 0 && (
          <div className="text-xs text-gray-400 mt-0.5">
            Affected: {node.affected_count} entities
          </div>
        )}
      </div>
      {(node.children ?? []).length > 0 && (
        <div className="ml-3 border-l border-gray-600 pl-3">
          {(node.children ?? []).map((child) => (
            <CascadeTree key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function CascadeVisualizerPanel({ incident }: { incident: Incident | null }) {
  if (!incident) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-400 text-sm">
        Select an incident to view its cascade tree
      </div>
    );
  }

  const depthColor =
    incident.cascade_depth >= 5
      ? "text-red-400"
      : incident.cascade_depth >= 4
        ? "text-amber-400"
        : "text-gray-400";

  return (
    <div className="bg-gray-800 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">Cascade Tree</h3>
        <span className={`text-xs ${depthColor}`}>
          Depth: {incident.cascade_depth} / 5 max
        </span>
      </div>
      {incident.cascade_tree ? (
        <CascadeTree node={incident.cascade_tree} />
      ) : (
        <div className="text-xs text-gray-400">No cascade data available</div>
      )}
    </div>
  );
}

export function CascadeModal({
  incident,
  onClose,
}: {
  incident: Incident | null;
  onClose: () => void;
}) {
  if (!incident) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div
        className="bg-gray-800 rounded-lg shadow-2xl w-[600px] max-h-[80vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Cascade tree"
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-bold text-white">
            Cascade Tree — {incident.type.replace(/_/g, " ")}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-xl"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="p-4">
          <div className="text-xs text-gray-400 mb-3">
            {incident.location} · Depth: {incident.cascade_depth}
          </div>
          {incident.cascade_tree ? (
            <CascadeTree node={incident.cascade_tree} />
          ) : (
            <div className="text-sm text-gray-400">
              No cascade data available for this incident.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
