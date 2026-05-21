import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import { formatEur } from "../../utils/formatCurrency";
import type { HourlyCostPoint } from "../../types";

export function HourlyCurveChart({ hours }: { hours: HourlyCostPoint[] }) {
  if (hours.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm text-center">
        No hourly data yet — hourly costs and revenues appear as the simulation
        progresses through the day.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={hours}>
        <defs>
          <linearGradient id="colorCost" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="hour"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(h: number) => `${h}:00`}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) => formatEur(v)}
        />
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          labelFormatter={(h) => `${h}:00`}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Area
          type="monotone"
          dataKey="cost_eur"
          name="Cost"
          stroke="#ef4444"
          fill="url(#colorCost)"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="revenue_eur"
          name="Revenue"
          stroke="#22c55e"
          fill="url(#colorRevenue)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
