import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { baggageApi } from "../hooks/useApi";
import type { BagDetail } from "../pages/Airport3D/model";

export function BaggageInspector({ zoneId }: { zoneId: string }) {
  const [params, setParams] = useSearchParams();
  const bagId = params.get("bag");
  const setBagId = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("bag", id);
    setParams(next, { replace: true });
  };
  const items = useQuery({
    queryKey: ["baggage", "3d-items", zoneId],
    queryFn: () => baggageApi.list({ zone: zoneId, limit: "50" }),
    refetchInterval: 5000,
  });
  const detail = useQuery({
    queryKey: ["baggage", "detail", bagId],
    queryFn: () => baggageApi.get(bagId!) as Promise<BagDetail>,
    enabled: !!bagId,
    refetchInterval: 5000,
  });
  return (
    <section
      className="border-t border-panel-border pt-4 space-y-3"
      aria-label="Recorded baggage items"
    >
      <h3 className="text-sm">Recorded items in this zone</h3>
      {items.isError && (
        <p role="alert" className="text-xs text-amber-300">
          Item records unavailable or stale.
        </p>
      )}
      {items.isLoading && (
        <p className="text-xs text-gray-400">Loading item records…</p>
      )}
      <p className="text-[11px] text-gray-500">
        Showing {items.data?.items.length ?? "—"} of {items.data?.total ?? "—"}.
        3D bags are aggregate representatives.
      </p>
      <div className="max-h-40 overflow-y-auto space-y-1">
        {items.data?.items.map((item) => (
          <button
            key={item.id}
            onClick={() => setBagId(item.id)}
            aria-pressed={bagId === item.id}
            className={`block text-left w-full rounded p-2 text-xs ${bagId === item.id ? "bg-sky-400/15 text-sky-200" : "bg-panel-active text-gray-400"}`}
          >
            {item.tag || item.id} · {item.status}
          </button>
        ))}
      </div>
      {items.data && !items.data.items.length && (
        <p className="text-xs text-gray-400">
          No item records currently match this zone.
        </p>
      )}
      {bagId && (
        <div className="space-y-2 text-xs">
          <p className="font-mono text-cyan-200">{detail.data?.tag || bagId}</p>
          {detail.isLoading && <p>Loading scan history…</p>}
          {detail.isError && (
            <p role="alert" className="text-amber-300">
              Scan history unavailable or stale.
            </p>
          )}
          {detail.data && (
            <>
              <p>
                {detail.data.status} · last scan:{" "}
                {detail.data.last_scan_zone || "Unknown"}
              </p>
              <ol className="space-y-2">
                {detail.data.scan_history?.map((scan, i) => (
                  <li
                    key={`${scan.at}-${i}`}
                    className="border-l border-cyan-400/40 pl-2"
                  >
                    <p>
                      {scan.zone} · {scan.status}
                    </p>
                    <time className="text-gray-500">{scan.at}</time>
                  </li>
                ))}
              </ol>
              {!detail.data.scan_history?.length && (
                <p className="text-gray-500">
                  No scan history recorded. Next destination unknown.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
