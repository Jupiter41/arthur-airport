import { useMemo } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { formatEur } from "../../utils/formatCurrency";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "./constants";

export function CostBreakdownChart({
  byCategory,
}: {
  byCategory: Record<string, number>;
}) {
  const data = useMemo(() => {
    return Object.entries(byCategory)
      .filter(([, v]) => v > 0)
      .map(([cat, val]) => ({
        name: CATEGORY_LABELS[cat] ?? cat,
        value: Math.round(val),
        fill: CATEGORY_COLORS[cat] ?? "#6b7280",
      }))
      .sort((a, b) => b.value - a.value);
  }, [byCategory]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm text-center">
        No cost breakdown yet — costs accumulate as flights land, depart, and
        are delayed.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          innerRadius="40%"
          outerRadius="75%"
          paddingAngle={2}
          stroke="none"
        >
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.fill} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }}
          iconType="circle"
          iconSize={8}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
