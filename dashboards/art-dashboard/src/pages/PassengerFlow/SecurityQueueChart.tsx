import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { PassengerFlowSummary } from "../../types";

export function SecurityQueueChart({
  summary,
}: {
  summary: PassengerFlowSummary | null;
}) {
  if (!summary?.security) return null;

  const data = Object.entries(summary.security).map(([term, info]) => ({
    terminal: `Terminal ${term.replace("terminal_", "")}`,
    queue: info.queue_length,
    wait: info.frozen ? 0 : info.wait_minutes,
    lanes: info.lanes_open,
    frozen: info.frozen ?? false,
  }));

  function barColor(wait: number): string {
    if (wait <= 10) return "#22c55e";
    if (wait <= 20) return "#f59e0b";
    return "#ef4444";
  }

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Security Queue Depth &amp; Wait Time
      </h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={data}
              margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="terminal"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
              />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={32} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #4b5563",
                  borderRadius: 4,
                }}
                labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                itemStyle={{ fontSize: 11, color: "#e5e7eb" }}
              />
              <Bar dataKey="queue" name="Queue Depth" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={barColor(d.wait)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={data}
              margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="terminal"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                width={32}
                unit=" min"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #4b5563",
                  borderRadius: 4,
                }}
                labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                itemStyle={{ fontSize: 11, color: "#e5e7eb" }}
                formatter={(value) => [`${value} min`, "Est. Wait"]}
              />
              <Bar dataKey="wait" name="Est. Wait" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={barColor(d.wait)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
