import { useState, useCallback, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { dataSourcesApi } from "../../hooks/useApi";
import { createPortal } from "react-dom";
import {
  SourceComparison,
  type SourceComparisonColumn,
  type SourceComparisonRow,
} from "../../components/SourceComparison";

/* ──────── Capacity Mismatch Warning (tooltip) ──────── */

export function CapacityMismatchWarning({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const [showTooltip, setShowTooltip] = useState(false);
  const warning = details.capacity_warning as string | undefined;
  const ratio = details.capacity_ratio as number | undefined;

  if (!warning) return null;

  return (
    <div className="mt-3 relative">
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-900/20 border border-amber-700/30 cursor-help"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <span className="text-amber-400 text-sm">⚠️</span>
        <span className="text-[10px] text-amber-300">
          Capacity mismatch detected
          {ratio ? ` (${Math.round(ratio * 100)}% utilization)` : ""}
        </span>
      </div>
      {showTooltip && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-72 p-3 rounded-lg bg-slate-800 border border-slate-600 shadow-xl text-xs text-slate-300">
          <p className="font-medium text-amber-300 mb-1">
            BTS Data / Airport Capacity Mismatch
          </p>
          <p className="text-slate-400 leading-relaxed">{warning}</p>
          <p className="text-slate-500 mt-2 text-[10px]">
            Tip: You can adjust the schedule offset in the sim-orchestrator
            settings or scale the BTS data to match the airport&apos;s
            gate/runway capacity.
          </p>
        </div>
      )}
    </div>
  );
}

/* ──────── Field metadata for chart labels ──────── */

const PASSENGER_FIELD_META: Record<
  string,
  { label: string; unit: string; description: string }
> = {
  total_passengers: {
    label: "Total Passengers",
    unit: "pax",
    description: "Total passenger count at this point in time",
  },
  departing_passengers: {
    label: "Departing Passengers",
    unit: "pax",
    description: "Passengers departing in the current hour",
  },
  arriving_passengers: {
    label: "Arriving Passengers",
    unit: "pax",
    description: "Passengers arriving in the current hour",
  },
  avg_load_factor: {
    label: "Average Load Factor",
    unit: "%",
    description: "Seat occupancy rate across all flights",
  },
};

const PAX_CHART_COLORS: Record<string, string> = {
  simulated: "#22d3ee",  // cyan-400
  bts: "#fbbf24",        // amber-400
};

interface PaxHistoryEntry {
  timestamp: number;
  simulated: Record<string, number | null>;
  bts: Record<string, number | null>;
}

/* ──────── Passenger Chart Modal ──────── */

function PassengerChartModal({
  history,
  chartField,
  setChartField,
  onClose,
}: {
  history: PaxHistoryEntry[];
  chartField: string;
  setChartField: (f: string) => void;
  onClose: () => void;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const fieldMeta = PASSENGER_FIELD_META[chartField] ?? {
    label: chartField,
    unit: "",
    description: "",
  };

  const sources = ["simulated", "bts"] as const;
  const width = 600;
  const height = 200;
  const pad = { top: 20, right: 20, bottom: 30, left: 60 };

  // Compute scales
  let allValues: number[] = [];
  for (const entry of history) {
    for (const src of sources) {
      const val = entry[src]?.[chartField];
      if (typeof val === "number") allValues.push(val);
    }
  }
  if (allValues.length === 0) allValues = [0, 1];
  const yMin = Math.min(0, Math.min(...allValues));
  const yMax = Math.max(...allValues) * 1.1 || 1;
  const yRange = yMax - yMin || 1;

  const xScale = (i: number) =>
    pad.left +
    (i / Math.max(1, history.length - 1)) * (width - pad.left - pad.right);
  const yScale = (v: number) =>
    pad.top + (1 - (v - yMin) / yRange) * (height - pad.top - pad.bottom);

  // Y-axis ticks
  const yTicks = Array.from({ length: 5 }, (_, i) =>
    yMin + (yRange * i) / 4,
  );

  // X-axis tick labels (timestamps)
  const xTicks =
    history.length >= 2
      ? [0, Math.floor(history.length / 2), history.length - 1]
      : history.length === 1
        ? [0]
        : [];

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose();
      }}
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl bg-slate-900 border border-slate-700 shadow-2xl p-6"
        role="dialog"
        aria-modal="true"
        aria-label="Passenger source comparison chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-100">
            📊 Passenger Source Comparison
          </h2>
          <button
            onClick={onClose}
            className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm"
            aria-label="Close"
          >
            ✕ Close
          </button>
        </div>

        {/* Field selector */}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-slate-400">Metric:</span>
          <select
            value={chartField}
            onChange={(e) => setChartField(e.target.value)}
            className="text-xs bg-slate-800 text-slate-200 rounded px-3 py-1.5 border border-slate-600"
          >
            {Object.entries(PASSENGER_FIELD_META).map(([key, meta]) => (
              <option key={key} value={key}>
                {meta.label} ({meta.unit})
              </option>
            ))}
          </select>
        </div>

        {/* Description */}
        <p className="text-[10px] text-slate-500 mb-3">
          {fieldMeta.description}.{" "}
          <span className="text-amber-500/80">
            Note: Simulation shows passengers currently in airport;
            BTS shows estimated hourly throughput based on historical monthly averages.
          </span>
        </p>

        {/* Chart */}
        {history.length < 2 ? (
          <div className="text-sm text-slate-500 py-8 text-center bg-slate-800/50 rounded-lg">
            Collecting data points… Chart will appear after 2+ comparisons
            (auto-refreshes every 15s).
          </div>
        ) : (
          <div className="relative bg-slate-800/50 rounded-lg p-3 mb-4">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              className="w-full"
              preserveAspectRatio="xMidYMid meet"
            >
              {/* Y-axis label */}
              <text
                x={12}
                y={height / 2}
                textAnchor="middle"
                className="fill-slate-400"
                fontSize="10"
                transform={`rotate(-90, 12, ${height / 2})`}
              >
                {fieldMeta.label} ({fieldMeta.unit})
              </text>
              {/* Y-axis ticks */}
              {yTicks.map((tick, i) => (
                <g key={i}>
                  <line
                    x1={pad.left}
                    x2={width - pad.right}
                    y1={yScale(tick)}
                    y2={yScale(tick)}
                    stroke="#334155"
                    strokeDasharray="3,3"
                  />
                  <text
                    x={pad.left - 5}
                    y={yScale(tick) + 3}
                    textAnchor="end"
                    className="fill-slate-500"
                    fontSize="9"
                  >
                    {fieldMeta.unit === "%"
                      ? `${(tick * 100).toFixed(0)}%`
                      : tick >= 1000
                        ? `${(tick / 1000).toFixed(1)}k`
                        : Math.round(tick)}
                  </text>
                </g>
              ))}
              {/* X-axis ticks */}
              {xTicks.map((idx) => (
                <text
                  key={idx}
                  x={xScale(idx)}
                  y={height - 5}
                  textAnchor="middle"
                  className="fill-slate-500"
                  fontSize="9"
                >
                  {new Date(history[idx].timestamp).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </text>
              ))}
              <text
                x={width / 2}
                y={height}
                textAnchor="middle"
                className="fill-slate-400"
                fontSize="10"
              >
                Time
              </text>
              {/* Lines + data points */}
              {sources.map((src) => {
                const points = history
                  .map((entry, i) => {
                    const val = entry[src]?.[chartField];
                    if (typeof val !== "number") return null;
                    return { x: xScale(i), y: yScale(val), val };
                  })
                  .filter(Boolean) as { x: number; y: number; val: number }[];
                if (points.length < 2) return null;
                return (
                  <g key={src}>
                    <polyline
                      points={points.map((p) => `${p.x},${p.y}`).join(" ")}
                      fill="none"
                      stroke={PAX_CHART_COLORS[src] ?? "#888"}
                      strokeWidth="2"
                      strokeLinejoin="round"
                    />
                    {points.map((p, i) => (
                      <circle
                        key={i}
                        cx={p.x}
                        cy={p.y}
                        r="3"
                        fill={PAX_CHART_COLORS[src] ?? "#888"}
                      >
                        <title>
                          {fieldMeta.label}: {p.val}
                          {fieldMeta.unit ? ` ${fieldMeta.unit}` : ""}
                        </title>
                      </circle>
                    ))}
                  </g>
                );
              })}
            </svg>
          </div>
        )}

        {/* Legend */}
        <div className="flex items-center gap-6 justify-center">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: PAX_CHART_COLORS.simulated }}
            />
            Simulation (in airport)
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: PAX_CHART_COLORS.bts }}
            />
            BTS Historical (hourly estimate)
          </div>
        </div>
      </div>
    </div>
  );
}

/* ──────── Passenger Comparison (uses shared SourceComparison) ──────── */

export function PassengerComparisonInline() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["passenger-compare"],
    queryFn: () =>
      dataSourcesApi.passengerCompare() as Promise<Record<string, unknown>>,
    refetchInterval: 15_000,
  });

  const [history, setHistory] = useState<PaxHistoryEntry[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [chartField, setChartField] = useState<string>("total_passengers");

  // Accumulate history for chart
  useEffect(() => {
    if (!data) return;
    const simulated = data.simulated as Record<string, unknown> | undefined;
    const bts = data.bts_historical as Record<string, unknown> | undefined;
    if (!simulated && !bts) return;

    const entry: PaxHistoryEntry = {
      timestamp: Date.now(),
      simulated: {},
      bts: {},
    };
    for (const field of Object.keys(PASSENGER_FIELD_META)) {
      entry.simulated[field] =
        typeof simulated?.[field] === "number"
          ? (simulated[field] as number)
          : null;
      entry.bts[field] =
        typeof bts?.[field] === "number" ? (bts[field] as number) : null;
    }
    setHistory((prev) => [...prev, entry].slice(-60));
  }, [data]);

  const simulated = data?.simulated as Record<string, unknown> | undefined;
  const bts = data?.bts_historical as Record<string, unknown> | undefined;

  const columns: SourceComparisonColumn[] = [
    {
      key: "simulated",
      label: "Simulation Engine",
      headerClass: "text-cyan-400",
      icon: "⚙️",
      isActive: true,
    },
    {
      key: "bts",
      label: "BTS T-100 Historical",
      headerClass: "text-amber-400",
      icon: "📊",
    },
  ];

  const fields = [
    "total_passengers",
    "departing_passengers",
    "arriving_passengers",
    "avg_load_factor",
  ];

  const rows: SourceComparisonRow[] = data
    ? fields.map((field) => ({
        field: field.replace(/_/g, " "),
        values: {
          simulated:
            simulated?.[field] != null
              ? typeof simulated[field] === "number"
                ? Number(simulated[field])
                : String(simulated[field])
              : null,
          bts:
            bts?.[field] != null
              ? typeof bts[field] === "number"
                ? Number(bts[field])
                : String(bts[field])
              : null,
        },
      }))
    : [];

  return (
    <>
      <SourceComparison
        source="Passengers"
        columns={columns}
        rows={rows}
        graphEnabled={true}
        onGraphClick={() => setShowModal(true)}
        loading={isLoading}
        onRefresh={() => { refetch(); }}
        description="Compares simulated passenger flow with BTS historical data. Sim = passengers currently in airport; BTS = estimated hourly throughput from monthly averages."
      />
      {showModal &&
        createPortal(
          <PassengerChartModal
            history={history}
            chartField={chartField}
            setChartField={setChartField}
            onClose={() => setShowModal(false)}
          />,
          document.body,
        )}
    </>
  );
}

/* ──────── Incident Comparison (uses shared SourceComparison) ──────── */

export function IncidentComparisonInline({
  currentSource,
}: {
  currentSource?: string;
}) {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["incident-compare"],
    queryFn: () =>
      dataSourcesApi.incidentCompare() as Promise<Record<string, unknown>>,
  });

  const deltas = data?.deltas as
    | Record<
        string,
        { simulated: number; asrs_historical: number; ratio: number | null }
      >
    | undefined;

  const columns: SourceComparisonColumn[] = [
    {
      key: "simulated",
      label: "Static probability model (internal)",
      headerClass: "text-cyan-400",
      icon: "🎲",
      isActive: currentSource === "simulated" || currentSource === "simulation",
    },
    {
      key: "asrs",
      label: "FAA ASRS",
      headerClass: "text-amber-400",
      icon: "🚨",
      isActive: currentSource === "asrs_historical",
    },
  ];

  const rows: SourceComparisonRow[] = deltas
    ? Object.entries(deltas).map(([type, d]) => ({
        field: type.replace(/_/g, " "),
        values: {
          simulated: d.simulated,
          asrs: d.asrs_historical,
        },
      }))
    : [];

  return (
    <SourceComparison
      source="Incidents"
      columns={columns}
      rows={rows}
      graphEnabled={false}
      loading={isLoading}
      onRefresh={() => { refetch(); }}
      description="Compares simulated incident probabilities with FAA ASRS calibrated data. Chart disabled — static probabilities have no time-series to plot."
    />
  );
}
