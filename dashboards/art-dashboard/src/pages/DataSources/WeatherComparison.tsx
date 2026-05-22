import { useState, useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { weatherApi } from "../../hooks/useApi";
import {
  SOURCE_DESCRIPTIONS,
  COMPARE_FIELDS,
  SOURCE_CHART_COLORS,
  type CompareField,
  type CompareResult,
  type HistoryEntry,
} from "./constants";
import { SourceComparison, SourceComparisonColumn, SourceComparisonRow } from "../../components/SourceComparison";

/* ──────── Mini SVG Chart for source comparison ──────── */

function MiniChart({
  history,
  field,
  sourceColors,
}: {
  history: HistoryEntry[];
  field: string;
  sourceColors: Record<string, string>;
}) {
  const sources = ["simulated", "historical", "live"];
  const width = 400;
  const height = 100;
  const pad = { top: 5, right: 5, bottom: 5, left: 35 };

  let allValues: number[] = [];
  for (const entry of history) {
    for (const src of sources) {
      const val = entry.sources[src]?.[field];
      if (typeof val === "number") allValues.push(val);
    }
  }
  if (allValues.length === 0) allValues = [0, 1];

  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);
  const yRange = yMax - yMin || 1;

  const xScale = (i: number) =>
    pad.left +
    (i / Math.max(1, history.length - 1)) * (width - pad.left - pad.right);
  const yScale = (v: number) =>
    pad.top + (1 - (v - yMin) / yRange) * (height - pad.top - pad.bottom);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-full"
      preserveAspectRatio="none"
    >
      <text
        x={pad.left - 3}
        y={pad.top + 4}
        textAnchor="end"
        className="fill-slate-500"
        fontSize="8"
      >
        {typeof yMax === "number" ? yMax.toFixed(1) : ""}
      </text>
      <text
        x={pad.left - 3}
        y={height - pad.bottom}
        textAnchor="end"
        className="fill-slate-500"
        fontSize="8"
      >
        {typeof yMin === "number" ? yMin.toFixed(1) : ""}
      </text>
      {sources.map((src) => {
        const points = history
          .map((entry, i) => {
            const val = entry.sources[src]?.[field];
            if (typeof val !== "number") return null;
            return `${xScale(i)},${yScale(val)}`;
          })
          .filter(Boolean);
        if (points.length < 2) return null;
        return (
          <polyline
            key={src}
            points={points.join(" ")}
            fill="none"
            stroke={sourceColors[src] ?? "#888"}
            strokeWidth="2"
            strokeLinejoin="round"
          />
        );
      })}
    </svg>
  );
}

/* ──────── Weather field metadata ──────── */

const WEATHER_FIELD_META: Record<
  string,
  { label: string; unit: string }
> = {
  visibility_m: { label: "Visibility", unit: "m" },
  wind_speed_kt: { label: "Wind Speed", unit: "kt" },
  wind_direction: { label: "Wind Direction", unit: "°" },
  temperature_c: { label: "Temperature", unit: "°C" },
  qnh_hpa: { label: "QNH (Pressure)", unit: "hPa" },
};

/* ──────── Comparison Modal ──────── */

function ComparisonModal({
  history,
  chartField,
  setChartField,
  sourceNames,
  currentSource,
  onClose,
}: {
  history: HistoryEntry[];
  chartField: string;
  setChartField: (f: string) => void;
  sourceNames: string[];
  currentSource: string;
  onClose: () => void;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const fieldMeta = WEATHER_FIELD_META[chartField] ?? {
    label: chartField,
    unit: "",
  };

  const sources = sourceNames;
  const width = 600;
  const height = 220;
  const pad = { top: 20, right: 20, bottom: 35, left: 60 };

  // Compute scales
  let allValues: number[] = [];
  for (const entry of history) {
    for (const src of sources) {
      const val = entry.sources[src]?.[chartField];
      if (typeof val === "number") allValues.push(val);
    }
  }
  if (allValues.length === 0) allValues = [0, 1];
  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);
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

  // X-axis tick labels
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
        aria-label="Weather source comparison chart"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-100">
            📊 Weather Source Comparison
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
            {COMPARE_FIELDS.filter((f) => f !== "category").map((f) => {
              const meta = WEATHER_FIELD_META[f];
              return (
                <option key={f} value={f}>
                  {meta ? `${meta.label} (${meta.unit})` : f}
                </option>
              );
            })}
          </select>
        </div>

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
              {/* Y-axis ticks + grid lines */}
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
                    {typeof tick === "number" ? tick.toFixed(1) : ""}
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
              {/* Lines + data point markers */}
              {sources.map((src) => {
                const points = history
                  .map((entry, i) => {
                    const val = entry.sources[src]?.[chartField];
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
                      stroke={SOURCE_CHART_COLORS[src] ?? "#888"}
                      strokeWidth="2"
                      strokeLinejoin="round"
                    />
                    {points.map((p, i) => (
                      <circle
                        key={i}
                        cx={p.x}
                        cy={p.y}
                        r="3"
                        fill={SOURCE_CHART_COLORS[src] ?? "#888"}
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
          {sourceNames.map((src) => (
            <div
              key={src}
              className="flex items-center gap-2 text-xs text-slate-400"
            >
              <span
                className="w-3 h-3 rounded-full"
                style={{
                  backgroundColor: SOURCE_CHART_COLORS[src] ?? "#888",
                }}
              />
              {SOURCE_DESCRIPTIONS[src]?.label ?? src}
              {src === currentSource && (
                <span className="text-[9px] bg-accent/20 text-accent px-1 rounded">
                  active
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ──────── Weather Comparison Panel ──────── */

const SOURCE_COLORS: Record<string, string> = {
  simulated: "text-cyan-400",
  historical: "text-amber-400",
  live: "text-emerald-400",
};

export function WeatherComparisonPanel({
  currentSource,
}: {
  currentSource: string;
}) {
  const [comparison, setComparison] = useState<CompareResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [chartField, setChartField] = useState<string>("temperature_c");

  const fetchComparison = useCallback(async () => {
    setLoading(true);
    try {
      const data = (await weatherApi.compare()) as CompareResult;
      setComparison(data);
      if (data.sim_time) {
        setHistory((prev) => {
          const entry: HistoryEntry = {
            timestamp: Date.now(),
            sources: {},
          };
          for (const [src, vals] of Object.entries(data.sources)) {
            if (vals.available) {
              entry.sources[src] = {};
              for (const f of COMPARE_FIELDS) {
                entry.sources[src][f] = vals[f as CompareField] ?? null;
              }
            }
          }
          const next = [...prev, entry];
          return next.slice(-60);
        });
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchComparison();
    const interval = setInterval(fetchComparison, 15000);
    return () => clearInterval(interval);
  }, [fetchComparison]);

  const sourceNames = comparison
    ? Object.keys(comparison.sources)
    : ["simulated", "historical", "live"];

  // Build columns and rows for the shared component
  const columns: SourceComparisonColumn[] = sourceNames.map((src) => ({
    key: src,
    label: SOURCE_DESCRIPTIONS[src]?.label ?? src,
    headerClass: SOURCE_COLORS[src] ?? "text-slate-400",
    icon: SOURCE_DESCRIPTIONS[src]?.icon ?? "❓",
    isActive: src === currentSource,
  }));

  const rows: SourceComparisonRow[] = comparison
    ? COMPARE_FIELDS.map((field) => ({
        field,
        values: Object.fromEntries(
          sourceNames.map((src) => {
            const srcData = comparison.sources[src];
            if (!srcData?.available) return [src, null];
            const raw = (srcData as unknown as Record<string, unknown>)?.[
              field
            ];
            const val =
              typeof raw === "number" || typeof raw === "string"
                ? raw
                : raw != null
                  ? String(raw)
                  : null;
            return [src, val];
          }),
        ),
      }))
    : [];

  // Chart modal rendered via portal
  return (
    <>
      <SourceComparison
        source="Weather"
        columns={columns}
        rows={rows}
        graphEnabled={true}
        onGraphClick={() => setShowModal(true)}
        loading={loading}
        onRefresh={fetchComparison}
        description={`Non-destructive comparison — reads from all sources without switching the active one. Active: ${currentSource}`}
      />
      {showModal &&
        createPortal(
          <ComparisonModal
            history={history}
            chartField={chartField}
            setChartField={setChartField}
            sourceNames={sourceNames}
            currentSource={currentSource}
            onClose={() => setShowModal(false)}
          />,
          document.body,
        )}
    </>
  );
}
