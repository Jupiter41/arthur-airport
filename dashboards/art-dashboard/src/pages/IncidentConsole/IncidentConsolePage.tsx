import { useState, useEffect, useMemo, useCallback } from "react";
import { useIncidentStore } from "../../stores/incidentStore";
import { useAnalysisStore } from "../../stores/analysisStore";
import { AutonomousPanel } from "../../components/AutonomousPanel";
import type {
  AnalysisBottleneck,
  AnalysisRecommendation,
} from "../../stores/analysisStore";
import { incidentsApi, analysisApi } from "../../hooks/useApi";
import {
  useIncidentConsoleQueries,
  useBottlenecksQuery,
  useRecommendationsQuery,
} from "../../hooks/useQueries";
import { StatusBadge } from "../../components/StatusBadge";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import WhatIfPanel from "./WhatIfPanel";
import {
  NLQueryPanel,
  NLInjectPanel,
  AnomalyPanel,
  NarrationFeed,
  ReportGenerator,
} from "./Phase5Panels";
import type { ExportFormat } from "../../utils/exportData";
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
          <div className="text-xs text-gray-400 mt-0.5">
            Affected: {node.affected_count} entities
          </div>
        )}
      </div>
      {/* Arrow if has children */}
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

/* ──────── Cascade Visualizer Panel ──────── */
function CascadeVisualizerPanel({ incident }: { incident: Incident | null }) {
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

/* ──────── Protocol Status Bar ──────── */
function ProtocolBar({ incident }: { incident: Incident | null }) {
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

/* ──────── Alert Feed ──────── */
function AlertFeed({ alerts }: { alerts: IncidentAlert[] }) {
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
      <div
        className="bg-gray-800 rounded-lg shadow-2xl w-[500px] max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Inject incident"
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-bold text-white">Inject Incident</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
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
function ResolvedList({
  incidents,
  onViewCascade,
}: {
  incidents: Incident[];
  onViewCascade: (id: string) => void;
}) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const handleDownload = useCallback(async (id: string) => {
    setDownloading(id);
    try {
      const report = await incidentsApi.report(id);
      const text =
        typeof report === "string" ? report : JSON.stringify(report, null, 2);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `incident-report-${id.slice(0, 8)}.json`;
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
              <span className="text-xs text-gray-400 font-mono">
                {formatSimTime(i.started_at)}
              </span>
              <span className="text-white">{i.type.replace(/_/g, " ")}</span>
              <StatusBadge status="resolved" />
              <span className="text-xs text-gray-400">{i.location}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="text-xs text-emerald-400 hover:text-emerald-300"
                onClick={() => onViewCascade(i.id)}
              >
                🌳 View Cascade
              </button>
              <button
                className="text-xs text-blue-400 hover:text-blue-300"
                onClick={() => handleDownload(i.id)}
                disabled={downloading === i.id}
              >
                {downloading === i.id ? "..." : "↓ Report"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Cascade Modal ──────── */
function CascadeModal({
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

/* ──────── P2-2-7: Recommendation Feed ──────── */

const SEVERITY_RING: Record<string, string> = {
  critical: "ring-red-500",
  warning: "ring-amber-500",
};

const ACTION_ICON: Record<string, string> = {
  open_security_lane: "🚪",
  early_gate_call: "📢",
  redirect_checkin: "🔄",
  reassign_gate: "🔀",
  delay_taxi: "⏸",
  swap_gates: "↔",
  hold_connecting_flight: "✋",
  fast_track_passengers: "⚡",
  rebook_passengers: "📋",
  ground_delay_program: "🛬",
  redistribute_vehicles: "🚛",
  defer_task: "⏳",
  redirect_baggage: "🧳",
  expedite_loading: "📦",
};

function RecommendationFeed({
  bottlenecks,
  recommendations,
}: {
  bottlenecks: AnalysisBottleneck[];
  recommendations: AnalysisRecommendation[];
}) {
  const [applying, setApplying] = useState<string | null>(null);

  if (bottlenecks.length === 0 && recommendations.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-400 text-sm">
        No active bottlenecks or recommendations
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Bottlenecks &amp; Recommendations
      </h3>

      {/* Active bottlenecks */}
      {bottlenecks.map((bn) => (
        <div
          key={bn.id}
          className={`border-l-4 ${
            bn.severity === "critical"
              ? "border-red-500 bg-red-900/20"
              : "border-amber-500 bg-amber-900/20"
          } rounded p-3`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white uppercase">
              {bn.type.replace(/_/g, " ")}
            </span>
            <StatusBadge status={bn.severity} />
          </div>
          <div className="text-sm text-gray-300 mt-1">{bn.root_cause}</div>
          <div className="text-xs text-gray-400 mt-1">
            {bn.affected_entity_count} affected · ~
            {bn.estimated_duration_minutes} min
          </div>
        </div>
      ))}

      {/* Recommendations */}
      {recommendations.map((rec) => (
        <div
          key={rec.id}
          className={`ring-1 ${
            SEVERITY_RING[
              bottlenecks.find((b) => b.id === rec.bottleneck_id)?.severity ??
                "warning"
            ] ?? "ring-gray-600"
          } bg-gray-800 rounded p-3`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm text-white font-medium">
              {ACTION_ICON[rec.action_type] ?? "💡"} {rec.description}
            </span>
            <span className="text-xs text-gray-400">#{rec.priority_rank}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-gray-400">
            <div>
              <span className="text-gray-400">Impact:</span>{" "}
              {rec.expected_impact}
            </div>
            <div>
              <span className="text-gray-400">Cost:</span> {rec.cost}
            </div>
          </div>
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-2">
              <div className="w-20 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    rec.confidence_score >= 0.8
                      ? "bg-green-500"
                      : rec.confidence_score >= 0.6
                        ? "bg-amber-500"
                        : "bg-red-500"
                  }`}
                  style={{ width: `${rec.confidence_score * 100}%` }}
                />
              </div>
              <span className="text-xs text-gray-400">
                {(rec.confidence_score * 100).toFixed(0)}% conf.
              </span>
            </div>
            {!rec.applied && (
              <button
                className="text-xs font-bold px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                disabled={applying === rec.id}
                onClick={async () => {
                  setApplying(rec.id);
                  try {
                    await analysisApi.whatIf({
                      actions: [
                        {
                          action_type: rec.action_type,
                          description: rec.description,
                          parameters: rec.parameters,
                        },
                      ],
                      horizon_minutes: 60,
                    });
                  } catch {
                    // silently ignore — projection-only
                  } finally {
                    setApplying(null);
                  }
                }}
              >
                {applying === rec.id ? "..." : "Apply"}
              </button>
            )}
            {rec.applied && (
              <span className="text-xs text-green-400">✓ Applied</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────── Tab bar ──────── */
const TABS = [
  { id: "ops", label: "Operations", icon: "🚨" },
  { id: "analysis", label: "Analysis", icon: "📊" },
  { id: "ai", label: "AI Tools", icon: "🤖" },
  { id: "autonomous", label: "Autonomous", icon: "⚙️" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/* ──────── Main Page ──────── */
export default function IncidentConsolePage() {
  const incidents = useIncidentStore((s) => s.incidents);
  const alerts = useIncidentStore((s) => s.alerts);
  const setIncidents = useIncidentStore((s) => s.setIncidents);
  const upsertIncident = useIncidentStore((s) => s.upsertIncident);
  const setAlerts = useIncidentStore((s) => s.setAlerts);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cascadeViewId, setCascadeViewId] = useState<string | null>(null);
  const [injectOpen, setInjectOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("ops");

  const queries = useIncidentConsoleQueries();
  const bnQuery = useBottlenecksQuery();
  const recQuery = useRecommendationsQuery();
  const storeBottlenecks = useAnalysisStore((s) => s.bottlenecks);
  const storeRecs = useAnalysisStore((s) => s.recommendations);

  useEffect(() => {
    const active = queries.active.data ?? [];
    const resolved = queries.resolved.data ?? [];
    if (active.length > 0 || resolved.length > 0) {
      setIncidents([...active, ...resolved]);
    }
  }, [queries.active.data, queries.resolved.data, setIncidents]);

  useEffect(() => {
    if (queries.alerts.data) setAlerts(queries.alerts.data);
  }, [queries.alerts.data, setAlerts]);

  // Fetch full incident detail (with cascade_tree) when an incident is selected
  useEffect(() => {
    const targetId = selectedId ?? cascadeViewId;
    if (!targetId) return;
    const existing = incidents[targetId];
    if (existing?.cascade_tree) return; // already have cascade data
    incidentsApi
      .get(targetId)
      .then((detail) => {
        if (detail && typeof detail === "object") {
          upsertIncident(detail as never);
        }
      })
      .catch(() => {});
  }, [selectedId, cascadeViewId, incidents, upsertIncident]);

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
  const cascadeViewIncident = cascadeViewId
    ? (incidents[cascadeViewId] ?? null)
    : null;

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Incident Operations</h2>
        <div className="flex items-center gap-3">
          <ExportMenu
            onExport={(fmt: ExportFormat) => {
              const rows = incidentList.map((i) => ({
                id: i.id,
                type: i.type,
                severity: i.severity,
                status: i.status,
                title: i.title,
                location: i.location,
                started_at: i.started_at,
                resolved_at: i.resolved_at ?? "",
                cascade_depth: i.cascade_depth,
                protocols: (i.protocols ?? []).join("; "),
              }));
              exportData(rows, "incidents", fmt);
            }}
          />
          <button
            className="text-sm font-bold px-4 py-2 rounded bg-red-600 text-white hover:bg-red-500"
            onClick={() => setInjectOpen(true)}
          >
            + INJECT
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-700 pb-0">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`text-sm font-medium px-4 py-2 rounded-t-lg transition-all duration-150 ${
              activeTab === tab.id
                ? "bg-gray-800 text-white border border-gray-700 border-b-gray-800 -mb-px"
                : "text-gray-400 hover:text-white hover:bg-gray-800/50"
            }`}
          >
            <span className="mr-1.5">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab: Operations ── */}
      {activeTab === "ops" && (
        <>
          {/* Main panel */}
          <div className="grid grid-cols-3 gap-4">
            {/* Active incidents */}
            <div className="space-y-3">
              <h3 className="text-xs text-gray-400 uppercase tracking-wide">
                Active Incidents ({activeIncidents.length})
              </h3>
              {activeIncidents.length === 0 && (
                <div className="text-sm text-gray-400">No active incidents</div>
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
          <ResolvedList
            incidents={resolvedIncidents}
            onViewCascade={(id) => setCascadeViewId(id)}
          />
        </>
      )}

      {/* ── Tab: Analysis ── */}
      {activeTab === "analysis" && (
        <>
          {/* Recommendation feed (P2-2-7) */}
          <RecommendationFeed
            bottlenecks={
              (bnQuery.data as AnalysisBottleneck[] | undefined) ??
              storeBottlenecks
            }
            recommendations={
              (recQuery.data as AnalysisRecommendation[] | undefined) ??
              storeRecs
            }
          />

          {/* What-If Analysis (P2-3-3) */}
          <WhatIfPanel />
        </>
      )}

      {/* ── Tab: AI Tools ── */}
      {activeTab === "ai" && (
        <>
          {/* P5-3-1: Anomaly Detection + P5-2-3: Narration */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AnomalyPanel />
            <NarrationFeed />
          </div>

          {/* P5-2-1: Natural Language Query */}
          <NLQueryPanel />

          {/* P5-2-2 + P5-2-4: NL Injection & Report */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <NLInjectPanel />
            <ReportGenerator />
          </div>
        </>
      )}

      {/* ── Tab: Autonomous ── */}
      {activeTab === "autonomous" && <AutonomousPanel />}

      {/* Cascade view modal */}
      {cascadeViewIncident && (
        <CascadeModal
          incident={cascadeViewIncident}
          onClose={() => setCascadeViewId(null)}
        />
      )}

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
