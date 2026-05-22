import { useState } from "react";
import type { DataSourceStatus } from "../../hooks/useApi";
import { SOURCE_DESCRIPTIONS, TYPE_COLORS, STATUS_STYLES } from "./constants";
import { WeatherComparisonPanel } from "./WeatherComparison";
import {
  CapacityMismatchWarning,
  PassengerComparisonInline,
  IncidentComparisonInline,
} from "./SourceComparisons";

export function SourceCard({
  source,
  onSwitch,
  isSwitching,
}: {
  source: DataSourceStatus;
  onSwitch: (sourceId: string, newSource: string) => void;
  isSwitching: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const statusStyle = STATUS_STYLES[source.status] ?? STATUS_STYLES.unavailable;
  const typeColor = TYPE_COLORS[source.type] ?? TYPE_COLORS.weather;
  const sourceInfo = SOURCE_DESCRIPTIONS[source.current_source] ?? {
    label: source.current_source,
    description: "Unknown source",
    icon: "❓",
  };

  return (
    <div
      className={`rounded-xl border bg-gradient-to-br ${typeColor} p-4 transition-all duration-200 hover:shadow-lg hover:shadow-black/20`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="text-2xl">{sourceInfo.icon}</div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              {source.name}
            </h3>
            <p className="text-xs text-slate-400">{source.service}</p>
          </div>
        </div>
        <div
          className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full ${statusStyle.bg}`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot} animate-pulse`}
          />
          <span
            className={`text-[10px] font-semibold uppercase ${statusStyle.text}`}
          >
            {source.status}
          </span>
        </div>
      </div>

      {/* Current source info */}
      <div className="mb-3 p-2 rounded-lg bg-slate-900/50">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Active:</span>
          <span className="text-xs font-semibold text-slate-200">
            {sourceInfo.label}
          </span>
        </div>
        <p className="text-[10px] text-slate-500 mt-0.5">
          {sourceInfo.description}
        </p>
      </div>

      {/* Available sources */}
      {source.available_sources.length > 1 && (
        <div className="mb-3">
          <p className="text-[10px] text-slate-400 mb-1.5 uppercase tracking-wide font-semibold">
            Switch source:
          </p>
          <div className="flex flex-wrap gap-1.5">
            {source.available_sources.map((s) => {
              const isActive = s === source.current_source;
              const sInfo = SOURCE_DESCRIPTIONS[s] ?? { label: s, icon: "❓" };
              const switchable =
                source.id === "weather" ||
                source.id === "passengers" ||
                source.id === "incidents";
              return (
                <button
                  key={s}
                  disabled={isActive || isSwitching || !switchable}
                  onClick={() => onSwitch(source.id, s)}
                  className={`px-2.5 py-1 text-[11px] rounded-lg transition-all border ${
                    isActive
                      ? "bg-accent/20 text-accent border-accent/40 cursor-default"
                      : switchable
                        ? "bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700 hover:border-slate-500"
                        : "bg-slate-800/50 text-slate-500 border-slate-700/50 cursor-not-allowed"
                  }`}
                  title={
                    !switchable && !isActive
                      ? "Source switching not yet implemented for this service"
                      : ""
                  }
                >
                  {sInfo.icon} {sInfo.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Details toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors"
      >
        {expanded ? "▾ Hide details" : "▸ Show details"}
      </button>

      {expanded && (
        <div className="mt-2 p-2 rounded-lg bg-slate-900/40 border border-slate-700/30">
          <pre className="text-[10px] text-slate-400 font-mono whitespace-pre-wrap overflow-x-auto">
            {JSON.stringify(source.details, null, 2)}
          </pre>
          {source.last_updated && (
            <p className="text-[10px] text-slate-500 mt-1">
              Last updated: {new Date(source.last_updated).toLocaleTimeString()}
            </p>
          )}
        </div>
      )}

      {/* Weather comparison panel */}
      {source.id === "weather" && source.status === "active" && (
        <WeatherComparisonPanel currentSource={source.current_source} />
      )}

      {/* BTS capacity mismatch warning */}
      {(source.id === "passengers" || source.id === "flights") &&
        source.current_source !== "simulation" &&
        source.current_source !== "simulated" &&
        !!source.details?.capacity_warning && (
          <CapacityMismatchWarning details={source.details} />
        )}

      {/* Passenger comparison (inside card) */}
      {source.id === "passengers" && source.status === "active" && (
        <PassengerComparisonInline />
      )}

      {/* Incident comparison (inside card) */}
      {source.id === "incidents" && source.status === "active" && (
        <IncidentComparisonInline currentSource={source.current_source} />
      )}
    </div>
  );
}
