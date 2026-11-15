import { useEffect, useState } from "react";
import { useConnectionStore } from "../stores/connectionStore";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

export function ConnectionStatus() {
  const state = useConnectionStore();
  const client = useQueryClient();
  const fetching = useIsFetching();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const queries = client
    .getQueryCache()
    .getAll()
    .filter((q) => q.getObserversCount() > 0);
  const failed = queries.filter((q) => q.state.status === "error");
  const observed = queries.filter((q) => q.state.dataUpdatedAt > 0);
  return (
    <details className="relative data-health">
      <summary className="cursor-pointer text-gray-300">
        {failed.length
          ? `${failed.length} observations unavailable`
          : state.wsConnected
            ? "Live connection"
            : "Live connection interrupted"}
      </summary>
      <div className="absolute right-0 top-full mt-2 w-80 max-w-[85vw] card z-50 space-y-2 text-xs">
        <p>
          Event stream: {state.wsConnected ? "connected" : "reconnecting"}.{" "}
          {fetching ? "Refreshing observations…" : "Observation requests idle."}
        </p>
        <p className="text-gray-400">
          Fetch ages below use real time. A paused simulated clock does not mean
          the connection is stale.
        </p>
        {observed.map((q) => (
          <p key={q.queryHash}>
            {q.queryKey.slice(0, 2).map(String).join(" / ")}: fetched{" "}
            {Math.max(0, Math.floor((now - q.state.dataUpdatedAt) / 1000))}s ago
            {q.state.status === "error" ? " · last refresh failed" : ""}
          </p>
        ))}
        {failed.length > 0 && (
          <p className="text-amber-300">
            Unavailable:{" "}
            {failed
              .map((q) => q.queryKey.slice(0, 2).map(String).join(" / "))
              .join(", ")}
          </p>
        )}
        {state.lastWsError && <p>{state.lastWsError}</p>}
      </div>
    </details>
  );
}
