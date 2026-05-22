import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from "recharts";
import type { DaySummary } from "./types";

export function FlightStatsChart({ days }: { days: DaySummary[] }) {
  if (days.length === 0) return null;

  const data = days.map((d) => ({
    name: `D${d.day_number}`,
    total: d.flights_total,
    delayed: d.flights_delayed,
    cancelled: d.flights_cancelled,
  }));

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Flights by Day
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 10 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={36} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #4b5563",
              borderRadius: 4,
            }}
            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
          <Bar
            dataKey="total"
            name="Total"
            fill="#3b82f6"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            dataKey="delayed"
            name="Delayed"
            fill="#f59e0b"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            dataKey="cancelled"
            name="Cancelled"
            fill="#ef4444"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DelayTrendChart({ days }: { days: DaySummary[] }) {
  if (days.length < 2) return null;

  const data = days.map((d) => ({
    name: `D${d.day_number}`,
    avg_delay: d.avg_delay_minutes,
    incidents: d.incidents_total,
  }));

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Delay & Incident Trend
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart
          data={data}
          margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 10 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={36} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #4b5563",
              borderRadius: 4,
            }}
            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
          <Line
            type="monotone"
            dataKey="avg_delay"
            name="Avg Delay (min)"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
          <Line
            type="monotone"
            dataKey="incidents"
            name="Incidents"
            stroke="#ef4444"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
