import { useState, useEffect, useMemo, useCallback } from "react";
import { useIncidentStore } from "../../stores/incidentStore";
import { incidentsApi } from "../../hooks/useApi";
import { StatusBadge } from "../../components/StatusBadge";
import type {
  Incident,
  IncidentAlert,
  CascadeNode,
  IncidentSeverity,
} from "../../types";

/* ──────── Severity border colors ──────── */
const SEVERITY_BORDER: Record<IncidentSeverity, string> = {
  critical: "border-red-600",
  high: "border-orange-500",
  medium: "border-amber-500",
  low: "border-gray-500",
};

const SEVERITY_BG: Record<IncidentSeverity, string> = {
  critical: "bg-red-900/30",
  high: "bg-orange-900/20",
  medium: "bg-amber-900/20",
  low: "bg-gray-800",
};

/* ──────── Incident Card ──────── */
function IncidentCard({
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
      {incident.protocols.length > 0 && (
        <div className="flex gap-1 mt-2">
          {incident.protocols.map((p) => (
            <span
              key={p}
              className="text-[10px] bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded"
            >
              {p}
            </span>
          ))}
        </div>
      )}
      <div className="text-[10px] text-gray-500 mt-1">
        ↓ {incident.cascade_depth} cascade
        {incident.cascade_depth !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

/* ──────── Cascade Tree Visualizer ──────── */
function CascadeTree({
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
          <div className="text-xs text-gray-500 mt-0.5">
            Affected: {node.affected_count} entities
          </div>
        )}
      </div>
      {/* Arrow if has children */}
      {node.children?.length > 0 && (
        <div className="ml-3 border-l border-gray-600 pl-3">
          {node.children.map((child) => (
            <CascadeTree key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ──────── Cascade Visualizer Panel ──────── */
function CascadeVisualizerPanel({ incident }: { incident: Incident | null }) {
  if (!incident) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-500 text-sm">
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
        <div className="text-xs text-gray-500">No cascade data available</div>
      )}
    </div>
  );
}

/* ──────── Protocol Status Bar ──────── */
function ProtocolBar({ incident }: { incident: Incident | null }) {
  if (!incident || incident.protocols.length === 0) return null;

  return (
    <div className="flex gap-2 flex-wrap">
      {incident.protocols.map((p) => (
        <div key={p} className="bg-gray-700 rounded px-3 py-1.5 text-xs">
          <span className="text-amber-400 mr-1">●</span>
          <span className="text-white font-medium">{p}</span>
        </div>
      ))}
    </div>
  );
}

/* ──────── Alert Feed ──────── */
function AlertFeed({ alerts }: { alerts: IncidentAlert[] }) {
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Alert Feed
      </h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {alerts.length === 0 && (
          <div className="text-xs text-gray-500">No alerts yet</div>
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
            <span className="text-gray-500 font-mono whitespace-nowrap">
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

/* ──────── Injection Modal ──────── */
const INCIDENT_TYPES = [
  "runway_incursion",
  "baggage_fire",
  "security_breach",
  "severe_weather",
  "system_failure",
] as const;

const SEVERITY_OPTIONS = ["low", "medium", "high", "critical"] as const;

const LOCATIONS: Record<string, string[]> = {
  runway_incursion: ["runway-09L", "runway-09R", "runway-27R", "runway-27L"],
  baggage_fire: [
    "make-up-A-1",
    "make-up-A-2",
    "make-up-A-3",
    "make-up-A-4",
    "make-up-A-5",
    "make-up-B-1",
    "make-up-B-2",
    "make-up-B-3",
    "make-up-B-4",
    "make-up-B-5",
    "make-up-C-1",
    "make-up-C-2",
    "make-up-C-3",
    "make-up-C-4",
    "make-up-C-5",
  ],
  security_breach: [
    "terminal-A",
    "terminal-B",
    "terminal-C",
    "airside-A",
    "airside-B",
    "airside-C",
  ],
  severe_weather: ["airport-wide"],
  system_failure: [
    "conveyor-sorting",
    "conveyor-induction-A",
    "conveyor-induction-B",
    "conveyor-induction-C",
    "power-A",
    "power-B",
    "power-C",
    "screening-unit-1",
    "screening-unit-2",
    "screening-unit-3",
    "screening-unit-4",
    "screening-unit-5",
    "screening-unit-6",
  ],
};

const EXPECTED_EFFECTS: Record<string, string> = {
  runway_incursion:
    "→ Runway closed immediately\n→ ~6 aircraft go-around / enter holding\n→ RUNWAY_STOP protocol activates\n→ ~18–34 min disruption",
  baggage_fire:
    "→ Affected make-up zone shut down\n→ Baggage rerouted to alternate zones\n→ BAGGAGE_HOLD protocol activates",
  security_breach:
    "→ Zone lockdown activated\n→ Passengers held in place\n→ TERMINAL_LOCKDOWN protocol possible",
  severe_weather:
    "→ Weather transitions to LIFR\n→ Arrival/departure rates reduced\n→ GROUND_STOP possible",
  system_failure:
    "→ Affected conveyor zone goes offline\n→ Baggage flow disrupted\n→ Recovery after TTR",
};

function InjectModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [type, setType] = useState<string>("runway_incursion");
  const [severity, setSeverity] = useState<string>("critical");
  const [location, setLocation] = useState<string>("");
  const [preview, setPreview] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const locs = LOCATIONS[type];
    if (locs?.length) setLocation(locs[0]);
  }, [type]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await incidentsApi.inject({ type, severity, location });
      onClose();
      setPreview(false);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
      <div className="bg-gray-800 rounded-lg shadow-2xl w-[500px] max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-bold text-white">Inject Incident</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            ✕
          </button>
        </div>

        {!preview ? (
          <div className="p-4 space-y-4">
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Event Type
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                {INCIDENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Severity
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                {SEVERITY_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Location
              </label>
              <select
                className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              >
                {(LOCATIONS[type] ?? []).map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="text-sm px-4 py-2 rounded bg-gray-600 text-white hover:bg-gray-500"
                onClick={onClose}
              >
                Cancel
              </button>
              <button
                className="text-sm px-4 py-2 rounded bg-amber-600 text-white hover:bg-amber-500 font-bold"
                onClick={() => setPreview(true)}
              >
                Preview →
              </button>
            </div>
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <div className="bg-gray-900 rounded p-3 text-sm">
              <div className="text-white font-bold mb-2">
                Injecting: {type.replace(/_/g, " ")} ({severity.toUpperCase()})
                on {location}
              </div>
              <div className="text-gray-300 whitespace-pre-line text-xs">
                {EXPECTED_EFFECTS[type] ??
                  "Effects will cascade based on severity and location."}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="text-sm px-4 py-2 rounded bg-gray-600 text-white hover:bg-gray-500"
                onClick={() => setPreview(false)}
              >
                ← Back
              </button>
              <button
                className="text-sm px-4 py-2 rounded bg-red-600 text-white hover:bg-red-500 font-bold"
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? "Injecting..." : "Confirm Inject"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────── Resolved Incidents Table ──────── */
function ResolvedList({ incidents }: { incidents: Incident[] }) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const handleDownload = useCallback(async (id: string) => {
    setDownloading(id);
    try {
      const report = await incidentsApi.report(id);
      const text =
        typeof report === "string" ? report : JSON.stringify(report, null, 2);
      const blob = new Blob([text], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `incident-report-${id.slice(0, 8)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(null);
    }
  }, []);

  if (incidents.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Resolved Today ({incidents.length})
      </h3>
      <div className="space-y-1">
        {incidents.map((i) => (
          <div
            key={i.id}
            className="flex items-center justify-between text-sm bg-gray-700 rounded p-2"
          >
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 font-mono">
                {formatSimTime(i.started_at)}
              </span>
              <span className="text-white">{i.type.replace(/_/g, " ")}</span>
              <StatusBadge status="resolved" />
              <span className="text-xs text-gray-400">{i.location}</span>
            </div>
            <button
              className="text-xs text-blue-400 hover:text-blue-300"
              onClick={() => handleDownload(i.id)}
              disabled={downloading === i.id}
            >
              {downloading === i.id ? "..." : "↓ Report"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Main Page ──────── */
export default function IncidentConsolePage() {
  const incidents = useIncidentStore((s) => s.incidents);
  const alerts = useIncidentStore((s) => s.alerts);
  const setIncidents = useIncidentStore((s) => s.setIncidents);
  const setAlerts = useIncidentStore((s) => s.setAlerts);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [injectOpen, setInjectOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [activeData, resolvedData, alertData] = await Promise.all([
          incidentsApi.list({ status: "active,contained" }),
          incidentsApi.list({ status: "resolved" }),
          incidentsApi.alerts(),
        ]);
        if (cancelled) {
          return;
        }
        const active =
          (activeData as { incidents: Incident[] }).incidents ?? [];
        const resolved =
          (resolvedData as { incidents: Incident[] }).incidents ?? [];
        setIncidents([...active, ...resolved]);
        const ad = alertData as { alerts?: IncidentAlert[] };
        setAlerts(
          ad.alerts ??
            (Array.isArray(alertData) ? (alertData as IncidentAlert[]) : []),
        );
      } catch {
        // Keep existing state and retry on next interval tick.
      }
    };

    void load();
    const interval = setInterval(() => {
      void load();
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setIncidents, setAlerts]);

  const incidentList = Object.values(incidents);
  const activeIncidents = useMemo(
    () =>
      incidentList.filter(
        (i) => i.status === "active" || i.status === "contained",
      ),
    [incidentList],
  );
  const resolvedIncidents = useMemo(
    () => incidentList.filter((i) => i.status === "resolved"),
    [incidentList],
  );

  const selectedIncident = selectedId ? (incidents[selectedId] ?? null) : null;

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Incident Operations</h2>
        <button
          className="text-sm font-bold px-4 py-2 rounded bg-red-600 text-white hover:bg-red-500"
          onClick={() => setInjectOpen(true)}
        >
          + INJECT
        </button>
      </div>

      {/* Main panel */}
      <div className="grid grid-cols-3 gap-4">
        {/* Active incidents */}
        <div className="space-y-3">
          <h3 className="text-xs text-gray-400 uppercase tracking-wide">
            Active Incidents ({activeIncidents.length})
          </h3>
          {activeIncidents.length === 0 && (
            <div className="text-sm text-gray-500">No active incidents</div>
          )}
          {activeIncidents.map((i) => (
            <IncidentCard
              key={i.id}
              incident={i}
              selected={selectedId === i.id}
              onSelect={() => setSelectedId(i.id)}
            />
          ))}
        </div>

        {/* Cascade visualizer + protocol bar */}
        <div className="col-span-2 space-y-3">
          <CascadeVisualizerPanel incident={selectedIncident} />
          <ProtocolBar incident={selectedIncident} />
        </div>
      </div>

      {/* Alert feed */}
      <AlertFeed alerts={alerts} />

      {/* Resolved */}
      <ResolvedList incidents={resolvedIncidents} />

      {/* Injection modal */}
      <InjectModal open={injectOpen} onClose={() => setInjectOpen(false)} />
    </div>
  );
}

/* ──────── Utils ──────── */
function formatRelativeTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 60000);
  if (diff < 1) return "just now";
  if (diff < 60) return `${diff} min ago`;
  return `${Math.floor(diff / 60)}h ${diff % 60}m ago`;
}

function formatSimTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}
