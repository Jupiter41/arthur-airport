import { useState, useCallback } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { incidentsApi } from "../../hooks/useApi";
import { formatSimTime } from "./utils";
import type { Incident } from "../../types";

export function ResolvedList({
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
              {i.resolution_reason === "recommendation_applied" && (
                <span className="text-[10px] bg-emerald-800 text-emerald-300 px-1.5 py-0.5 rounded">
                  ⚡ Recommendation
                </span>
              )}
              {i.resolution_reason === "ttr_elapsed" && (
                <span className="text-[10px] bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded">
                  ⏱ TTR elapsed
                </span>
              )}
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
