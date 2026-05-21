import { useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { dataSourcesApi, weatherApi } from "../../hooks/useApi";
import { useWeatherStore } from "../../stores/weatherStore";
import type { WeatherState } from "../../types";
import { SourceCard } from "./SourceCard";

/* ──────── Main Page ──────── */

export default function DataSourcesPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["data-sources"],
    queryFn: () => dataSourcesApi.list(),
    refetchInterval: 15000,
  });

  const switchMutation = useMutation({
    mutationFn: ({
      sourceId,
      source,
    }: {
      sourceId: string;
      source: string;
    }) => {
      if (sourceId === "passengers") {
        return dataSourcesApi.switchPassengerSource(source);
      }
      if (sourceId === "incidents") {
        return dataSourcesApi.switchIncidentSource(source);
      }
      return dataSourcesApi.switchWeatherSource(source);
    },
    onSuccess: async (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["data-sources"] });
      if (variables.sourceId === "weather") {
        queryClient.invalidateQueries({ queryKey: ["weather-source"] });
        queryClient.invalidateQueries({ queryKey: ["weather"] });
        try {
          const fresh = await weatherApi.current();
          if (fresh) {
            useWeatherStore.getState().setCurrent(fresh as WeatherState);
          }
        } catch {
          /* weather will arrive via next WS event */
        }
      }
      if (variables.sourceId === "passengers") {
        queryClient.invalidateQueries({ queryKey: ["passenger-flow"] });
      }
      if (variables.sourceId === "incidents") {
        queryClient.invalidateQueries({ queryKey: ["incidents"] });
        queryClient.invalidateQueries({ queryKey: ["alerts"] });
      }
    },
  });

  const sources = data?.sources ?? [];

  const stats = useMemo(() => {
    const active = sources.filter((s) => s.status === "active").length;
    const degraded = sources.filter((s) => s.status === "degraded").length;
    const unavailable = sources.filter(
      (s) => s.status === "unavailable",
    ).length;
    const realSources = sources.filter(
      (s) =>
        s.current_source !== "simulation" &&
        s.current_source !== "simulated" &&
        s.current_source !== "disabled",
    ).length;
    return {
      active,
      degraded,
      unavailable,
      total: sources.length,
      realSources,
    };
  }, [sources]);

  const handleSwitch = (sourceId: string, newSource: string) => {
    switchMutation.mutate({ sourceId, source: newSource });
  };

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <span className="text-xl">🔌</span> Data Sources
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Manage and monitor data providers feeding the digital twin. Switch
            between simulation and real-world sources at runtime.
          </p>
        </div>
        {data && (
          <div className="text-[10px] text-slate-500">
            Last refresh: {new Date(data.timestamp).toLocaleTimeString()}
          </div>
        )}
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/40 p-3 text-center">
          <div className="text-lg font-bold text-slate-100">{stats.total}</div>
          <div className="text-[10px] text-slate-400 uppercase tracking-wide">
            Total Sources
          </div>
        </div>
        <div className="rounded-xl bg-emerald-900/30 border border-emerald-700/30 p-3 text-center">
          <div className="text-lg font-bold text-emerald-400">
            {stats.active}
          </div>
          <div className="text-[10px] text-emerald-400/70 uppercase tracking-wide">
            Active
          </div>
        </div>
        <div className="rounded-xl bg-amber-900/30 border border-amber-700/30 p-3 text-center">
          <div className="text-lg font-bold text-amber-400">
            {stats.degraded}
          </div>
          <div className="text-[10px] text-amber-400/70 uppercase tracking-wide">
            Degraded
          </div>
        </div>
        <div className="rounded-xl bg-red-900/30 border border-red-700/30 p-3 text-center">
          <div className="text-lg font-bold text-red-400">
            {stats.unavailable}
          </div>
          <div className="text-[10px] text-red-400/70 uppercase tracking-wide">
            Unavailable
          </div>
        </div>
        <div className="rounded-xl bg-cyan-900/30 border border-cyan-700/30 p-3 text-center">
          <div className="text-lg font-bold text-cyan-400">
            {stats.realSources}
          </div>
          <div className="text-[10px] text-cyan-400/70 uppercase tracking-wide">
            Real-World
          </div>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-xl bg-red-900/20 border border-red-700/40 p-4 text-sm text-red-300">
          Failed to load data sources: {(error as Error).message}
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="text-center text-slate-400 text-sm py-8 animate-pulse">
          Loading data sources...
        </div>
      )}

      {/* Source Cards Grid */}
      {!isLoading && sources.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              onSwitch={handleSwitch}
              isSwitching={switchMutation.isPending}
            />
          ))}
        </div>
      )}

      {/* Switching feedback */}
      {switchMutation.isPending && (
        <div className="fixed bottom-4 right-4 rounded-xl bg-blue-900/90 border border-blue-600/50 px-4 py-3 text-sm text-blue-200 shadow-xl backdrop-blur-sm animate-pulse">
          Switching data source...
        </div>
      )}
      {switchMutation.isError && (
        <div className="fixed bottom-4 right-4 rounded-xl bg-red-900/90 border border-red-600/50 px-4 py-3 text-sm text-red-200 shadow-xl backdrop-blur-sm">
          Switch failed: {(switchMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
