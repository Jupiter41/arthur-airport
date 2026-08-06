import { useState, useEffect, useMemo } from "react";
import { useIncidentStore } from "../../stores/incidentStore";
import { useAnalysisStore } from "../../stores/analysisStore";
import { AutonomousPanel } from "../../components/AutonomousPanel";
import type {
  AnalysisBottleneck,
  AnalysisRecommendation,
} from "../../stores/analysisStore";
import { incidentsApi } from "../../hooks/useApi";
import {
  useIncidentConsoleQueries,
  useBottlenecksQuery,
  useRecommendationsQuery,
} from "../../hooks/useQueries";
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
import { IncidentCard } from "./IncidentCard";
import { IncidentActions } from "./IncidentActions";
import { CascadeVisualizerPanel, CascadeModal } from "./CascadeTree";
import { ProtocolBar } from "./ProtocolBar";
import { AlertFeed } from "./AlertFeed";
import { InjectModal } from "./InjectModal";
import { ResolvedList } from "./ResolvedList";
import { RecommendationFeed } from "./RecommendationFeed";
import { ApprovalQueue } from "./ApprovalQueue";
import { TABS } from "./constants";
import type { TabId } from "./constants";
import type { ExportFormat } from "../../utils/exportData";

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

  useEffect(() => {
    const targetId = selectedId ?? cascadeViewId;
    if (!targetId) return;
    const existing = incidents[targetId];
    if (existing?.cascade_tree) return;
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
          <div className="grid grid-cols-3 gap-4">
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

            <div className="col-span-2 space-y-3">
              {selectedIncident && (
                <IncidentActions incident={selectedIncident} />
              )}
              <CascadeVisualizerPanel incident={selectedIncident} />
              <ProtocolBar incident={selectedIncident} />
            </div>
          </div>

          <AlertFeed alerts={alerts} />

          <ResolvedList
            incidents={resolvedIncidents}
            onViewCascade={(id) => setCascadeViewId(id)}
          />
        </>
      )}

      {/* ── Tab: Analysis ── */}
      {activeTab === "analysis" && (
        <>
          <ApprovalQueue />

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

          <WhatIfPanel />
        </>
      )}

      {/* ── Tab: AI Tools ── */}
      {activeTab === "ai" && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AnomalyPanel />
            <NarrationFeed />
          </div>

          <NLQueryPanel />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <NLInjectPanel />
            <ReportGenerator />
          </div>
        </>
      )}

      {/* ── Tab: Autonomous ── */}
      {activeTab === "autonomous" && <AutonomousPanel />}

      {cascadeViewIncident && (
        <CascadeModal
          incident={cascadeViewIncident}
          onClose={() => setCascadeViewId(null)}
        />
      )}

      <InjectModal open={injectOpen} onClose={() => setInjectOpen(false)} />
    </div>
  );
}
