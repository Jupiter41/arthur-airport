import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { costsApi } from "../../hooks/useApi";
import { useSimStore } from "../../stores/simStore";
import { KpiCard } from "../../components/KpiCard";
import { LoadingState, ErrorState } from "../../components/LoadingState";

const SOURCE_COLORS: Record<string, string> = {
  apu: "#ef4444",
  taxi: "#f97316",
  ground_vehicle: "#eab308",
  terminal: "#3b82f6",
  passenger_road: "#22c55e",
  flight_segment: "#a855f7",
};

const fmtKg = (kg: number) => {
  if (kg >= 1000) return `${(kg / 1000).toFixed(2)} t`;
  return `${kg.toFixed(0)} kg`;
};

export default function CarbonPage() {
  const dayNumber = useSimStore((s) => s.status.day_number);
  const day = dayNumber ?? 1;
  const [gpu, setGpu] = useState(50);
  const [ev, setEv] = useState(40);
  const [solar, setSolar] = useState(20);

  const summary = useQuery({
    queryKey: ["carbon", "summary"],
    queryFn: () => costsApi.carbonSummary(),
    refetchInterval: 15_000,
  });
  const bySource = useQuery({
    queryKey: ["carbon", "by-source", day],
    queryFn: () => costsApi.carbonBySource(day),
    refetchInterval: 15_000,
  });
  const timeline = useQuery({
    queryKey: ["carbon", "timeline", day],
    queryFn: () => costsApi.carbonTimeline(day),
    refetchInterval: 15_000,
  });

  const scenario = useMutation({
    mutationFn: () =>
      costsApi.carbonScenario({
        gpu_adoption_pct: gpu / 100,
        ev_adoption_pct: ev / 100,
        solar_offset_pct: solar / 100,
      }),
  });

  if (summary.isLoading) return <LoadingState message="Loading carbon data…" />;
  if (summary.isError)
    return (
      <ErrorState
        message="Failed to load carbon data"
        detail="cost-service may be offline."
        onRetry={() => summary.refetch()}
      />
    );

  const total = summary.data?.total_co2_kg ?? 0;
  const sources = bySource.data?.sources ?? [];
  const pieData = sources.map((s) => ({
    name: s.source,
    value: Math.round(s.total_kg),
    fill: SOURCE_COLORS[s.source] ?? "#6b7280",
  }));
  const hourlyData = (timeline.data?.hours ?? []).map((h) => ({
    hour: `${String(h.hour).padStart(2, "0")}:00`,
    co2_kg: Math.round(h.co2_kg),
  }));
  const dominant =
    sources.length > 0
      ? sources.reduce((a, b) => (a.total_kg > b.total_kg ? a : b))
      : null;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">🌱 Carbon Footprint</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          ICAO Carbon Calculator + ACI ACA — Day {day}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <KpiCard
          label="Total CO₂ today"
          value={fmtKg(total)}
          sub={`${summary.data?.record_count ?? 0} events`}
          color="text-emerald-300"
        />
        <KpiCard
          label="Dominant source"
          value={dominant?.source ?? "—"}
          sub={
            dominant
              ? `${((dominant.total_kg / Math.max(total, 1)) * 100).toFixed(1)}%`
              : ""
          }
        />
        <KpiCard
          label="APU emissions"
          value={fmtKg(summary.data?.by_source?.apu ?? 0)}
        />
        <KpiCard
          label="Ground vehicles"
          value={fmtKg(summary.data?.by_source?.ground_vehicle ?? 0)}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface-card border border-panel-border rounded-xl p-4 h-80">
          <h2 className="text-sm font-semibold text-white mb-2">
            CO₂ by source
          </h2>
          {pieData.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              No emissions recorded yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="90%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius="40%"
                  outerRadius="75%"
                  paddingAngle={2}
                  stroke="none"
                >
                  {pieData.map((e, i) => (
                    <Cell key={i} fill={e.fill} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: unknown) => `${v} kg`}
                  contentStyle={{
                    backgroundColor: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: 8,
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
                  iconType="circle"
                  iconSize={8}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-surface-card border border-panel-border rounded-xl p-4 h-80">
          <h2 className="text-sm font-semibold text-white mb-2">
            Hourly timeline (kg CO₂)
          </h2>
          {hourlyData.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              No hourly samples yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="90%">
              <LineChart data={hourlyData}>
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis dataKey="hour" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: 8,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="co2_kg"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="bg-surface-card border border-panel-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-3">
          What-if mitigation scenario
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {[
            { label: "GPU adoption", value: gpu, set: setGpu },
            { label: "EV ground fleet", value: ev, set: setEv },
            { label: "Solar offset", value: solar, set: setSolar },
          ].map((s) => (
            <label key={s.label} className="text-xs text-gray-300">
              <div className="flex justify-between">
                <span>{s.label}</span>
                <span className="text-emerald-300 font-mono">{s.value}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={s.value}
                onChange={(e) => s.set(Number(e.target.value))}
                className="w-full mt-1"
              />
            </label>
          ))}
        </div>
        <button
          onClick={() => scenario.mutate()}
          disabled={scenario.isPending}
          className="text-xs bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white px-3 py-1.5 rounded"
        >
          {scenario.isPending ? "Computing…" : "Run scenario"}
        </button>
        {scenario.data && (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
            <KpiCard
              label="Baseline"
              value={fmtKg(scenario.data.baseline_kg)}
            />
            <KpiCard
              label="Projected"
              value={fmtKg(scenario.data.projected_kg)}
              color="text-emerald-300"
            />
            <KpiCard
              label="Saved"
              value={`${fmtKg(scenario.data.saved_kg)} (${scenario.data.saved_pct.toFixed(1)}%)`}
              color="text-emerald-400"
            />
          </div>
        )}
      </div>
    </div>
  );
}
