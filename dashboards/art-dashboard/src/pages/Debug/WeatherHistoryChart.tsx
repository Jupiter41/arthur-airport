import { useQuery } from "@tanstack/react-query";
import { weatherApi } from "../../hooks/useApi";
import { CATEGORY_COLORS } from "./helpers";

export function WeatherHistoryChart() {
  const { data } = useQuery({
    queryKey: ["weather-history"],
    queryFn: () => weatherApi.history(12),
    refetchInterval: 30000,
  });

  const states =
    (
      data as {
        states?: {
          category: string;
          from: string;
          to: string;
          duration_minutes: number;
        }[];
      }
    )?.states ?? [];

  if (states.length === 0) {
    return (
      <p className="text-xs text-gray-400">No weather history available</p>
    );
  }

  const totalMinutes =
    states.reduce((sum, s) => sum + s.duration_minutes, 0) || 720;

  return (
    <div className="space-y-1">
      <h4 className="text-xs text-gray-400 font-semibold">
        12h Weather History
      </h4>
      <div className="flex h-6 rounded overflow-hidden">
        {states.map((s, i) => {
          const widthPct = Math.max(
            1,
            (s.duration_minutes / totalMinutes) * 100,
          );
          return (
            <div
              key={i}
              className="relative group"
              style={{
                width: `${widthPct}%`,
                backgroundColor: CATEGORY_COLORS[s.category] ?? "#6b7280",
              }}
              title={`${s.category} — ${s.duration_minutes}min`}
            >
              {widthPct > 8 && (
                <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-white/80">
                  {s.category}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-gray-400">
        <span>
          {states[0]?.from ? new Date(states[0].from).toLocaleTimeString() : ""}
        </span>
        <span>
          {states[states.length - 1]?.to
            ? new Date(states[states.length - 1].to).toLocaleTimeString()
            : ""}
        </span>
      </div>
    </div>
  );
}
