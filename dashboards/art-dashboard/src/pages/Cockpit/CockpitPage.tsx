import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  flightsApi,
  incidentsApi,
  passengersApi,
  baggageApi,
} from "../../hooks/useApi";
import { useFlightStore } from "../../stores/flightStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { useConnectionStore } from "../../stores/connectionStore";
import type {
  Flight,
  Gate,
  Runway,
  Incident,
  PassengerFlowSummary,
  BaggageZone,
} from "../../types";
import { formatTime } from "../FlightBoard/helpers";
import { parseSimTime } from "../../utils/simTime";
import { normalizeGate } from "../Airport3D/model";
import { useSimStore } from "../../stores/simStore";
import { normalizeTerminal } from "../Airport3D/model";

import { ObservationTime } from "../../components/ObservationTime";

import { ApprovalQueue } from "../IncidentConsole/ApprovalQueue";

export default function CockpitPage() {
  const flights = useFlightStore((s) => s.flights);
  const gates = useFlightStore((s) => s.gates);
  const runways = useFlightStore((s) => s.runways);
  const incidents = useIncidentStore((s) => s.incidents);
  const wsConnected = useConnectionStore((s) => s.wsConnected);
  // REST reconciles the live stores; components do not read a parallel copy.
  const flightLoad = useQuery({
    queryKey: ["flights", "cockpit"],
    queryFn: async () =>
      (await flightsApi.list({ limit: "500" })).flights as Flight[],
    refetchInterval: 30_000,
  });
  const gateLoad = useQuery({
    queryKey: ["gates"],
    queryFn: async () =>
      (await flightsApi.gates()).gates.map((g) => normalizeGate(g as Gate)),
    refetchInterval: 30_000,
  });
  const runwayLoad = useQuery({
    queryKey: ["runways"],
    queryFn: async () => (await flightsApi.runways()).runways as Runway[],
    refetchInterval: 15_000,
  });
  const incidentLoad = useQuery({
    queryKey: ["incidents", "active"],
    queryFn: async () =>
      (await incidentsApi.list({ status: "active,contained" }))
        .incidents as Incident[],
    refetchInterval: 30_000,
  });
  const passenger = useQuery({
    queryKey: ["passengers", "summary"],
    queryFn: () => passengersApi.summary() as Promise<PassengerFlowSummary>,
    refetchInterval: 5000,
  });
  const baggage = useQuery({
    queryKey: ["baggage", "map"],
    queryFn: async () =>
      ((await baggageApi.map()) as { zones: BaggageZone[] }).zones,
    refetchInterval: 5000,
  });
  useEffect(() => {
    if (flightLoad.data) useFlightStore.getState().setFlights(flightLoad.data);
  }, [flightLoad.data]);
  useEffect(() => {
    if (gateLoad.data) useFlightStore.getState().setGates(gateLoad.data);
  }, [gateLoad.data]);
  useEffect(() => {
    if (runwayLoad.data) useFlightStore.getState().setRunways(runwayLoad.data);
  }, [runwayLoad.data]);
  useEffect(() => {
    if (incidentLoad.data)
      useIncidentStore.getState().setIncidents(incidentLoad.data);
  }, [incidentLoad.data]);
  const activeFlights = Object.values(flights).filter(
    (f) =>
      !["completed", "arrived", "cancelled", "diverted"].includes(f.status),
  );
  const activeIncidents = Object.values(incidents).filter(
    (i) => i.status !== "resolved",
  );
  const security = passenger.data?.security;
  const waits = security
    ? Object.values(security).map((s) => s.wait_minutes)
    : [];
  const degraded = [
    flightLoad.isError && "Flights",
    gateLoad.isError && "Gates",
    runwayLoad.isError && "Runways",
    incidentLoad.isError && "Incidents",
    passenger.isError && "Passengers",
    baggage.isError && "Baggage",
  ].filter(Boolean);
  const metric = (ready: boolean, value: number) =>
    ready ? String(value) : "—";
  const severityOrder: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3,
  };
  const [params, setParams] = useSearchParams();
  const scope = params.get("terminal") ?? "all";
  const clock = useSimStore((s) => s.status);
  const time = clock.tick_count > 0 ? clock.sim_time : "";
  const seconds = parseSimTime(time).getTime();
  const terminalEntries = Object.entries(security ?? {}).filter(
    ([key]) => scope === "all" || normalizeTerminal(key) === scope,
  );
  const peakTerminal = Object.entries(security ?? {}).sort(
    (a, b) => b[1].wait_minutes - a[1].wait_minutes,
  )[0]?.[0];
  const issues = [
    ...activeIncidents
      .filter(
        (i) =>
          scope === "all" ||
          i.location.toUpperCase().includes(`-${scope}`) ||
          i.location === "airport-wide",
      )
      .map((i) => ({
        id: i.id,
        observedAt: i.observed_at,
        priority: severityOrder[i.severity] ?? 4,
        title: i.title || i.type?.replace(/_/g, " ") || "Incident details unavailable",
        location: i.location,
        detail: `${i.description || "Affected-entity impact not supplied."} · Started ${formatTime(i.started_at)} UTC`,
        href: `/incidents?incident=${encodeURIComponent(i.id)}`,
        action: "Inspect incident",
      })),
    ...terminalEntries
      .filter(([, v]) => v.wait_minutes >= 20 || v.frozen)
      .map(([key, v]) => ({
        id: key,
        observedAt: v.observed_at,
        priority: v.frozen ? 1 : 2,
        title: v.frozen
          ? "Security lanes frozen"
          : "Security wait above 20 min",
        location: `Terminal ${normalizeTerminal(key)}`,
        detail: `${v.wait_minutes.toFixed(1)} min wait · ${v.queue_length} queued · ${v.lanes_open} lanes`,
        href: `/passengers?terminal=${normalizeTerminal(key)}&mode=board`,
        action: "Review queue & proposals",
      })),
    ...(baggage.data ?? [])
      .filter(
        (z) =>
          scope === "all" ||
          z.zone_id.toUpperCase().split(/[-_]/).includes(scope) ||
          !/[-_][ABC](?:[-_]|$)/i.test(z.zone_id),
      )
      .filter((z) => z.utilisation_pct > 90 || z.status === "offline")
      .map((z) => ({
        id: z.zone_id,
        observedAt: z.observed_at,
        priority: z.status === "offline" ? 1 : 3,
        title:
          z.status === "offline"
            ? "Conveyor offline"
            : "Conveyor above 90% capacity",
        location: z.zone_id,
        detail: `${z.items} bags · ${z.utilisation_pct.toFixed(0)}% utilisation`,
        href: `/baggage?entity=${encodeURIComponent(z.zone_id)}`,
        action: "Inspect conveyor",
      })),
  ].sort(
    (a, b) => a.priority - b.priority || a.location.localeCompare(b.location),
  );
  const upcoming = activeFlights
    .filter(
      (f) =>
        (scope === "all" ||
          normalizeTerminal(f.terminal || f.gate_id?.[0] || "") === scope) &&
        parseSimTime(f.estimated_time || f.scheduled_time).getTime() >= seconds &&
        parseSimTime(f.estimated_time || f.scheduled_time).getTime() <= seconds + 3600000,
    )
    .sort(
      (a, b) =>
        parseSimTime(a.estimated_time || a.scheduled_time).getTime() -
        parseSimTime(b.estimated_time || b.scheduled_time).getTime(),
    );
  return (
    <div className="page-container space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="section-label">
            Arthur International · shared simulation
          </p>
          <h1 className="mt-1">Airport overview</h1>
          <p className="text-sm text-gray-400 mt-2">
            Current exceptions, airport conditions and actions awaiting a
            response.
          </p>
        </div>
        <label className="text-sm">
          Terminal{" "}
          <select
            value={scope}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              next.set("terminal", e.target.value);
              setParams(next);
            }}
          >
            <option value="all">All terminals</option>
            {["A", "B", "C"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </header>
      {degraded.length > 0 && (
        <p
          role="alert"
          className="border border-amber-400/30 rounded-md p-3 text-sm text-amber-300"
        >
          Unavailable or stale: {degraded.join(", ")}. Last successful
          observations remain visible where available.
        </p>
      )}
      {!wsConnected && (
        <p className="text-sm text-gray-400">
          Live connection interrupted. Periodic observation requests continue.
        </p>
      )}
      <div
        className="flex flex-wrap gap-x-8 gap-y-3 py-3 border-y border-panel-border"
        aria-label="Airport-wide indicators"
      >
        {[
          [
            "Active flights",
            metric(!!flightLoad.data, activeFlights.length),
            "/flights",
          ],
          [
            "Delayed >15 min",
            metric(
              !!flightLoad.data,
              activeFlights.filter((f) => f.delay_minutes > 15).length,
            ),
            "/flights?view=delayed",
          ],
          [
            "Peak security wait",
            waits.length ? `${Math.max(...waits).toFixed(1)} min` : "—",
            peakTerminal
              ? `/passengers?terminal=${normalizeTerminal(peakTerminal)}`
              : "/passengers",
          ],
          [
            "Active incidents",
            metric(!!incidentLoad.data, activeIncidents.length),
            "/incidents",
          ],
        ].map(([label, value, href]) => (
          <Link key={label} to={href} className="hover:text-accent">
            <span className="block text-xs text-gray-400">
              {label} · airport-wide
            </span>
            <strong className="block text-2xl tabular-nums mt-1">
              {value}
            </strong>
          </Link>
        ))}
      </div>
      <div className="grid xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-5 items-start">
        <section className="card space-y-4" aria-label="Needs attention">
          <div className="flex justify-between">
            <h2>Needs attention · {issues.length}</h2>
            <span className="text-xs text-gray-400">
              Severity · queue pressure · location
            </span>
          </div>
          <div className="max-h-[380px] overflow-y-auto pr-1">
            {issues.map((issue) => (
              <Link
                key={issue.id}
                to={issue.href}
                className="block border-t border-panel-border py-3 hover:bg-panel"
              >
                <div className="flex justify-between gap-3">
                  <h3>{issue.title}</h3>
                  <span
                    className={
                      issue.priority <= 1
                        ? "text-red-400 text-xs"
                        : "text-amber-300 text-xs"
                    }
                  >
                    {issue.priority === 0
                      ? "Critical"
                      : issue.priority === 1
                        ? "High"
                        : "Review"}
                  </span>
                </div>
                <p className="text-sm mt-1">{issue.location}</p>
                <p className="text-sm text-gray-400 mt-1">{issue.detail}</p>
                <ObservationTime value={issue.observedAt} />
                <p className="text-accent text-sm mt-3">{issue.action} →</p>
              </Link>
            ))}
          </div>
          {!issues.length && (
            <p className="text-gray-400 text-sm">
              {degraded.length
                ? "No exceptions in available observations. Missing data prevents an all-clear assessment."
                : flightLoad.isLoading ||
                    passenger.isLoading ||
                    incidentLoad.isLoading
                  ? "Loading airport observations…"
                  : "No exceptions above the displayed thresholds in the latest observations."}
            </p>
          )}
          <p className="text-xs text-gray-400">
            Security ≥20 min or frozen; conveyor &gt;90% or offline; active
            incidents. Counts use current observations, not forecasts.
          </p>
        </section>
        <section className="card space-y-4" aria-label="Airport context">
          <div className="flex justify-between">
            <h2>Airfield & terminals</h2>
            <Link className="text-sm text-accent" to="/ground-ops?mode=map">
              Open map →
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {runways.map((r) => (
              <Link
                key={r.runway_id}
                to={`/ground-ops?mode=map&entity=${encodeURIComponent(r.runway_id)}`}
                className="block bg-panel-active border border-dashed border-panel-border rounded-md p-3"
              >
                <div className="flex justify-between gap-3">
                  <span className="font-mono">{r.runway_id}</span>
                  <span
                    className={
                      r.status === "closed" ? "text-red-400" : "text-gray-300"
                    }
                  >
                    {r.status}
                  </span>
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  {r.current_rate ?? "—"}/{r.capacity_per_hour ?? "—"}{" "}
                  movements/h
                </p>
              </Link>
            ))}
          </div>
          {!runways.length && (
            <p className="text-sm text-gray-400">
              Runway observations unavailable.
            </p>
          )}
          <div className="grid sm:grid-cols-3 gap-3">
            {["A", "B", "C"]
              .filter((t) => scope === "all" || t === scope)
              .map((t) => {
                const gs = gates.filter(
                  (g) =>
                    normalizeTerminal(g.terminal || g.gate_id?.[0] || "") === t,
                );
                const sec = Object.entries(security ?? {}).find(
                  ([key]) => normalizeTerminal(key) === t,
                )?.[1];
                return (
                  <Link
                    key={t}
                    className="rounded-md border border-panel-border p-3 hover:bg-panel"
                    to={`/passengers?terminal=${t}`}
                  >
                    <h3>Terminal {t}</h3>
                    <p className="text-sm mt-2">
                      {sec
                        ? `${sec.wait_minutes.toFixed(1)} min wait`
                        : "Wait unavailable"}
                    </p>
                    <p className="text-xs text-gray-400 mt-2">
                      {gateLoad.data
                        ? `${gs.filter((g) => g.flight_id || activeFlights.some((f) => f.gate_id === g.gate_id)).length}/${gs.length} gates occupied`
                        : "Gates unavailable"}
                    </p>
                  </Link>
                );
              })}
          </div>
          <p className="text-xs text-gray-400">
            Schematic airport context · select a terminal or runway to
            investigate.
          </p>
        </section>
      </div>
      <div className="grid xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-5 items-start">
        <section className="card space-y-3">
          <h2>Next 60 simulated minutes</h2>
          <p className="text-xs text-gray-400">
            Scheduled/estimated movements from the loaded flight board · not a
            forecast. Simulation time: {time || "unavailable"}.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead>
                <tr className="text-gray-400">
                  <th className="py-2">Flight</th>
                  <th>Time · UTC</th>
                  <th>Gate</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {upcoming.slice(0, 10).map((f) => (
                  <tr key={f.id} className="border-t border-panel-border">
                    <td className="py-3">
                      <Link
                        className="text-accent"
                        to={`/flights?flight=${encodeURIComponent(f.id)}`}
                      >
                        {f.flight_number}
                      </Link>
                    </td>
                    <td>{formatTime(f.estimated_time || f.scheduled_time)}</td>
                    <td>{f.gate_id ?? "Unassigned"}</td>
                    <td>{f.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!upcoming.length && (
            <p className="text-gray-400">
              {flightLoad.data
                ? "No loaded movements in this time window."
                : "Flight observations unavailable."}
            </p>
          )}
        </section>
        <section className="card">
          <ApprovalQueue pendingOnly />
        </section>
      </div>
    </div>
  );
}
