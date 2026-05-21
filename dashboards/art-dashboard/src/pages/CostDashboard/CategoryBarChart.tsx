import { useMemo } from "react";
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
import { formatEur } from "../../utils/formatCurrency";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "./constants";

export function CategoryBarChart({
  byCategory,
}: {
  byCategory: Record<string, number>;
}) {
  const data = useMemo(() => {
    return Object.entries(byCategory)
      .filter(([, v]) => v > 0)
      .map(([cat, val]) => ({
        category: CATEGORY_LABELS[cat] ?? cat,
        amount: Math.round(val),
        fill: CATEGORY_COLORS[cat] ?? "#6b7280",
      }))
      .sort((a, b) => b.amount - a.amount);
  }, [byCategory]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        No data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical">
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#334155"
          horizontal={false}
        />
        <XAxis
          type="number"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) => formatEur(v)}
        />
        <YAxis
          type="category"
          dataKey="category"
          stroke="#64748b"
          tick={{ fontSize: 10 }}
          width={120}
        />
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Bar dataKey="amount" name="Amount" radius={[0, 4, 4, 0]}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
