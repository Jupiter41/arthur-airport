import { formatEur } from "../../utils/formatCurrency";
import type { IncidentCostRanking } from "../../types";

export function IncidentRankingTable({
  incidents,
}: {
  incidents: IncidentCostRanking[];
}) {
  if (incidents.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-4">
        No incident costs recorded
      </div>
    );
  }

  return (
    <div className="overflow-auto max-h-full">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-400 text-xs uppercase tracking-wider border-b border-panel-border">
            <th className="text-left py-2 px-2">Type</th>
            <th className="text-right py-2 px-2">Direct</th>
            <th className="text-right py-2 px-2">Response</th>
            <th className="text-right py-2 px-2 font-bold">Total</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => (
            <tr
              key={inc.incident_id}
              className="border-b border-panel-border/50 hover:bg-panel-hover/30"
            >
              <td className="py-2 px-2 text-gray-300">
                {inc.type.replace(/_/g, " ")}
              </td>
              <td className="py-2 px-2 text-right text-red-400">
                {formatEur(inc.direct_eur)}
              </td>
              <td className="py-2 px-2 text-right text-orange-400">
                {formatEur(inc.response_eur)}
              </td>
              <td className="py-2 px-2 text-right font-bold text-white">
                {formatEur(inc.total_eur)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
