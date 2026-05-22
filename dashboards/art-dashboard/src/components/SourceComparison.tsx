/**
 * Shared source comparison component used across weather, incidents, and
 * passenger data source cards.
 *
 * Renders a comparison table with configurable columns + optional graph toggle.
 */

import type { ReactNode } from "react";

/* ── Types ────────────────────────────────────────────────── */

export interface SourceComparisonColumn {
  /** Identifier used to key data from rows */
  key: string;
  /** Display label in column header */
  label: string;
  /** Colour class for the header text */
  headerClass?: string;
  /** Icon prepended to the label */
  icon?: string;
  /** Whether this column is the currently active source */
  isActive?: boolean;
}

export interface SourceComparisonRow {
  /** Field name (first column) */
  field: string;
  /** Value per source column, keyed by SourceComparisonColumn.key */
  values: Record<string, string | number | null>;
}

export interface SourceComparisonProps {
  /** Source identifier label (e.g. "Weather", "Passengers") */
  source: string;
  /** Column definitions (one per data source) */
  columns: SourceComparisonColumn[];
  /** Row data (one per metric field) */
  rows: SourceComparisonRow[];
  /** Whether the graph button is enabled (visible but greyed out when false) */
  graphEnabled: boolean;
  /** Callback when the graph button is clicked */
  onGraphClick?: () => void;
  /** Optional extra content rendered below the table (e.g. inline chart) */
  graphComponent?: ReactNode;
  /** Whether data is currently loading */
  loading?: boolean;
  /** Optional callback when refresh is clicked */
  onRefresh?: () => void;
  /** Optional descriptive text below the header */
  description?: string;
}

/* ── Component ────────────────────────────────────────────── */

export function SourceComparison({
  columns,
  rows,
  graphEnabled,
  onGraphClick,
  graphComponent,
  loading = false,
  onRefresh,
  description,
}: SourceComparisonProps) {
  return (
    <div className="mt-4 p-4 rounded-xl bg-slate-800/60 border border-slate-700/50">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">
          📊 Source Comparison
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={onGraphClick}
            disabled={!graphEnabled}
            className="text-[10px] px-2 py-1 rounded bg-slate-700 text-slate-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed enabled:hover:bg-slate-600"
            title={
              graphEnabled
                ? "Show chart"
                : "Chart not available for this source"
            }
          >
            📈 Chart
          </button>
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={loading}
              className="text-[10px] px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors disabled:opacity-40"
            >
              {loading ? "..." : "↻ Refresh"}
            </button>
          )}
        </div>
      </div>

      {description && (
        <p className="text-[10px] text-slate-500 mb-3">{description}</p>
      )}

      {/* Table view */}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-2 px-2 text-slate-400 font-medium">
                  Field
                </th>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className={`text-left py-2 px-2 font-medium ${col.headerClass ?? "text-slate-400"}`}
                  >
                    {col.icon && <>{col.icon} </>}
                    {col.label}
                    {col.isActive && (
                      <span className="ml-1 text-[8px] bg-accent/20 text-accent px-1 rounded">
                        active
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const numValues = columns
                  .map((c) => row.values[c.key])
                  .filter((v): v is number => typeof v === "number");
                const allSame =
                  numValues.length >= 2 &&
                  numValues.every((v) => v === numValues[0]);
                const maxDiff =
                  numValues.length >= 2
                    ? Math.round(
                        (Math.max(...numValues) - Math.min(...numValues)) * 10,
                      ) / 10
                    : null;

                return (
                  <tr
                    key={row.field}
                    className={`border-b border-slate-800 ${
                      maxDiff !== null && !allSame ? "bg-amber-900/10" : ""
                    }`}
                  >
                    <td className="py-1.5 px-2 font-mono text-slate-300">
                      {row.field}
                    </td>
                    {columns.map((col) => {
                      const val = row.values[col.key];
                      return (
                        <td
                          key={col.key}
                          className={`py-1.5 px-2 ${val == null ? "text-slate-600 italic" : "text-slate-200"}`}
                        >
                          {val == null ? "N/A" : String(val)}
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

      {/* Optional graph / chart below the table */}
      {graphComponent}

      {/* Loading / empty states */}
      {loading && rows.length === 0 && (
        <div className="text-xs text-slate-500 py-3 text-center">
          Loading comparison data…
        </div>
      )}
      {!loading && rows.length === 0 && (
        <div className="text-xs text-slate-500 py-3 text-center">
          {onRefresh
            ? "Click Refresh to compare sources."
            : "No comparison data available."}
        </div>
      )}
    </div>
  );
}
