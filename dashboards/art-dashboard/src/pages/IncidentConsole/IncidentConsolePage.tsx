import { useQuery } from "@tanstack/react-query";
import { useState, useEffect, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DecisionWorkspace } from "../Decisions/DecisionWorkspace";
import { useIncidentStore } from "../../stores/incidentStore";
import { AutonomousPanel } from "../../components/AutonomousPanel";
import type {
  Incident,
  AnalysisBottleneck,
  AnalysisRecommendation,
} from "../../types";
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
  AnomalyPanel,
  NarrationFeed,
  ReportGenerator,
} from "./Phase5Panels";
import { IncidentCard } from "./IncidentCard";
import { IncidentActions } from "./IncidentActions";
import { CascadeVisualizerPanel, CascadeModal } from "./CascadeTree";
import { ProtocolBar } from "./ProtocolBar";
import { AlertFeed } from "./AlertFeed";
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
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("incident");
  const setSelectedId = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("incident", id);
    setParams(next, { replace: true });
  };
  const [cascadeViewId, setCascadeViewId] = useState<string | null>(null);
  const activeTab = (params.get("tab") ?? "ops") as TabId;
  const setActiveTab = (tab: TabId) => {
    const next = new URLSearchParams(params);
    next.set("tab", tab);
    setParams(next, { replace: true });
  };

  const queries = useIncidentConsoleQueries();
  // Bottlenecks and recommendations: React Query is the single source of
  // truth (polls the analysis REST endpoints). No WebSocket-fed duplicate.
  const bnQuery = useBottlenecksQuery();
  const recQuery = useRecommendationsQuery();

  useEffect(() => {
    const active = queries.active.data ?? [];
    const resolved = queries.resolved.data ?? [];
    if (queries.active.data && queries.resolved.data) {
      const rows = [...active, ...resolved];
      const selected = selectedId
        ? useIncidentStore.getState().incidents[selectedId]
        : undefined;
      setIncidents(
        selected && !rows.some((i) => i.id === selected.id)
          ? [...rows, selected]
          : rows,
      );
    }
  }, [queries.active.data, queries.resolved.data, setIncidents]);

  useEffect(() => {
    if (queries.alerts.data) setAlerts(queries.alerts.data);
  }, [queries.alerts.data, setAlerts]);

  const targetId = selectedId ?? cascadeViewId;
  const detailQuery = useQuery({
    queryKey: ["incidents", "detail", targetId],
    queryFn: () => incidentsApi.get(targetId!) as Promise<Incident>,
    enabled: !!targetId,
    refetchInterval: 30000,
  });
  useEffect(() => {
    if (detailQuery.data) upsertIncident(detailQuery.data);
  }, [detailQuery.data, upsertIncident]);

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
      <div className="flex flex-wrap items-center justify-between gap-3">
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
          {import.meta.env.VITE_PUBLIC_DEPLOYMENT !== "true" && (
            <Link className="btn-secondary text-sm" to="/lab">
              Open incident lab
            </Link>
          )}
        </div>
      </div>

      {(queries.active.isError || queries.resolved.isError) && (
        <p role="alert" className="text-amber-300">
          Incident observations unavailable or stale. Empty lists do not
          establish an all-clear state.
        </p>
      )}
      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 border-b border-gray-700 pb-0">
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
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab: Operations ── */}
      {activeTab === "ops" && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="space-y-3">
              <h3 className="text-xs text-gray-400 uppercase tracking-wide">
                Active Incidents ({activeIncidents.length})
              </h3>
              {activeIncidents.length === 0 && (
                <div className="text-sm text-gray-400">
                  {queries.active.isError
                    ? "Active incidents unavailable."
                    : queries.active.isLoading
                      ? "Loading incidents…"
                      : "No active incidents in the latest observation."}
                </div>
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

            <div className="xl:col-span-2 space-y-3">
              {detailQuery.isError && (
                <p role="alert" className="text-amber-300">
                  Incident details unavailable or stale.{" "}
                  <button
                    className="btn-secondary"
                    onClick={() => void detailQuery.refetch()}
                  >
                    Retry
                  </button>
                </p>
              )}
              {selectedIncident && (
                <IncidentActions incident={selectedIncident} />
              )}
              <CascadeVisualizerPanel incident={selectedIncident} />
              <ProtocolBar incident={selectedIncident} />
              {selectedIncident && (
                <DecisionWorkspace compact incidentId={selectedIncident.id} />
              )}
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
              (bnQuery.data as AnalysisBottleneck[] | undefined) ?? []
            }
            recommendations={
              (recQuery.data as AnalysisRecommendation[] | undefined) ?? []
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
            <Link className="card text-accent" to="/lab">
              Create synthetic incidents in the shared-airport lab →
            </Link>
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
    </div>
  );
}
