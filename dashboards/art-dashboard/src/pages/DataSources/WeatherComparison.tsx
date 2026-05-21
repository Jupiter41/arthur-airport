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

/* ──────── Comparison Modal ──────── */

function ComparisonModal({
  history,
  comparison,
  chartField,
  setChartField,
  sourceNames,
  currentSource,
  onClose,
}: {
  history: HistoryEntry[];
  comparison: CompareResult | null;
  chartField: string;
  setChartField: (f: string) => void;
  sourceNames: string[];
  currentSource: string;
  onClose: () => void;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose();
      }}
    >
      <div
        className="w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-xl bg-slate-900 border border-slate-700 shadow-2xl p-6"
        role="dialog"
        aria-modal="true"
        aria-label="Weather source comparison"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-100">
            📊 Weather Source Comparison
          </h2>
          <button
            onClick={onClose}
            className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm"
          >
            ✕ Close
          </button>
        </div>

        {/* Field selector */}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-slate-400">Chart field:</span>
          <select
            value={chartField}
            onChange={(e) => setChartField(e.target.value)}
            className="text-xs bg-slate-800 text-slate-200 rounded px-3 py-1.5 border border-slate-600"
          >
            {COMPARE_FIELDS.filter((f) => f !== "category").map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        {/* Large chart */}
        {history.length < 2 ? (
          <div className="text-sm text-slate-500 py-8 text-center bg-slate-800/50 rounded-lg">
            Collecting data points… Chart will appear after 2+ comparisons
            (auto-refreshes every 15s).
          </div>
        ) : (
          <div className="relative h-64 bg-slate-800/50 rounded-lg p-3 mb-4">
            <MiniChart
              history={history}
              field={chartField}
              sourceColors={SOURCE_CHART_COLORS}
            />
          </div>
        )}

        {/* Legend */}
        <div className="flex items-center gap-6 mb-6 justify-center">
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

        {/* Full comparison table */}
        {comparison && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-2 px-3 text-slate-400 font-medium">
                    Field
                  </th>
                  {sourceNames.map((src) => (
                    <th
                      key={src}
                      className="text-left py-2 px-3 font-medium"
                      style={{ color: SOURCE_CHART_COLORS[src] ?? "#94a3b8" }}
                    >
                      {SOURCE_DESCRIPTIONS[src]?.icon ?? "❓"}{" "}
                      {SOURCE_DESCRIPTIONS[src]?.label ?? src}
                    </th>
                  ))}
                  <th className="text-left py-2 px-3 text-slate-400 font-medium">
                    Δ max
                  </th>
                </tr>
              </thead>
              <tbody>
                {COMPARE_FIELDS.map((field) => {
                  const values = sourceNames.map(
                    (src) =>
                      (
                        comparison.sources[src] as unknown as Record<
                          string,
                          unknown
                        >
                      )?.[field],
                  );
                  const allSame =
                    values.every((v) => v === values[0]) &&
                    values.every((v) => v != null);
                  const numValues = values.filter(
                    (v) => typeof v === "number",
                  ) as number[];
                  const maxDiff =
                    numValues.length >= 2
                      ? Math.round(
                          (Math.max(...numValues) - Math.min(...numValues)) *
                            10,
                        ) / 10
                      : null;

                  return (
                    <tr
                      key={field}
                      className={`border-b border-slate-800 ${!allSame ? "bg-amber-900/10" : ""}`}
                    >
                      <td className="py-2 px-3 font-mono text-slate-300">
                        {field}
                      </td>
                      {sourceNames.map((src) => {
                        const srcData = comparison.sources[src];
                        if (!srcData?.available) {
                          return (
                            <td
                              key={src}
                              className="py-2 px-3 text-slate-600 italic"
                            >
                              N/A
                            </td>
                          );
                        }
                        return (
                          <td key={src} className="py-2 px-3 text-slate-200">
                            {String(
                              (srcData as unknown as Record<string, unknown>)?.[
                                field
                              ] ?? "—",
                            )}
                          </td>
                        );
                      })}
                      <td className="py-2 px-3 text-amber-400 text-xs">
                        {maxDiff !== null && !allSame ? `Δ${maxDiff}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────── Weather Comparison Panel ──────── */

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

  const SOURCE_COLORS: Record<string, string> = {
    simulated: "text-cyan-400",
    historical: "text-amber-400",
    live: "text-emerald-400",
  };

  return (
    <div className="mt-4 p-4 rounded-xl bg-slate-800/60 border border-slate-700/50">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">
          📊 Source Comparison
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowModal(true)}
            className="text-[10px] px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
          >
            📈 Chart
          </button>
          <button
            onClick={fetchComparison}
            disabled={loading}
            className="text-[10px] px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors disabled:opacity-40"
          >
            {loading ? "..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      <p className="text-[10px] text-slate-500 mb-3">
        Non-destructive comparison — reads from all sources without switching
        the active one. Active:{" "}
        <span className="text-slate-300">{currentSource}</span>
      </p>

      {comparison && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-2 px-2 text-slate-400 font-medium">
                  Field
                </th>
                {sourceNames.map((src) => (
                  <th
                    key={src}
                    className={`text-left py-2 px-2 font-medium ${SOURCE_COLORS[src] ?? "text-slate-400"}`}
                  >
                    {SOURCE_DESCRIPTIONS[src]?.icon ?? "❓"}{" "}
                    {SOURCE_DESCRIPTIONS[src]?.label ?? src}
                    {src === currentSource && (
                      <span className="ml-1 text-[8px] bg-accent/20 text-accent px-1 rounded">
                        active
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARE_FIELDS.map((field) => {
                const values = sourceNames.map(
                  (src) =>
                    (
                      comparison.sources[src] as unknown as Record<
                        string,
                        unknown
                      >
                    )?.[field],
                );
                const allSame =
                  values.every((v) => v === values[0]) &&
                  values.every((v) => v != null);
                const numValues = values.filter(
                  (v) => typeof v === "number",
                ) as number[];
                const maxDiff =
                  numValues.length >= 2
                    ? Math.round(
                        (Math.max(...numValues) - Math.min(...numValues)) * 10,
                      ) / 10
                    : null;

                return (
                  <tr
                    key={field}
                    className={`border-b border-slate-800 ${!allSame ? "bg-amber-900/10" : ""}`}
                  >
                    <td className="py-1.5 px-2 font-mono text-slate-300">
                      {field}
                    </td>
                    {sourceNames.map((src) => {
                      const srcData = comparison.sources[src];
                      if (!srcData?.available) {
                        return (
                          <td
                            key={src}
                            className="py-1.5 px-2 text-slate-600 italic"
                          >
                            N/A
                          </td>
                        );
                      }
                      return (
                        <td key={src} className="py-1.5 px-2 text-slate-200">
                          {String(
                            (srcData as unknown as Record<string, unknown>)?.[
                              field
                            ] ?? "—",
                          )}
                        </td>
                      );
                    })}
                    {maxDiff !== null && !allSame && (
                      <td className="py-1.5 px-2 text-amber-400 text-[10px]">
                        Δ{maxDiff}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showModal &&
        createPortal(
          <ComparisonModal
            history={history}
            comparison={comparison}
            chartField={chartField}
            setChartField={setChartField}
            sourceNames={sourceNames}
            currentSource={currentSource}
            onClose={() => setShowModal(false)}
          />,
          document.body,
        )}

      {!comparison && !loading && (
        <div className="text-xs text-slate-500 py-3 text-center">
          Click Refresh to compare weather across all sources.
        </div>
      )}
    </div>
  );
}
