import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { eventHandlers } from "../hooks/useWebSocket";
import { reconcileLiveQueries, resetLiveProjectionGuards, RECONCILE_WINDOW_MS } from "../hooks/liveProjections";
import { queryClient } from "../queryClient";
import { useBaggageStore } from "../stores/baggageStore";

// RC9: the gateway only delivers the event types in its policy file; the
// dashboard registry must handle exactly those.
const policy = JSON.parse(readFileSync(
  resolve(__dirname, "../../../../services/api-gateway/src/wsDeliveryPolicy.json"), "utf8",
)) as Record<string, string[] | string>;
const delivered = new Set(["immediate", "latest", "hint"].flatMap(k => policy[k] as string[]));

describe("RC9 UI delivery contract", () => {
  it("handles every delivered event type and nothing the gateway drops", () => {
    expect(new Set(Object.keys(eventHandlers))).toEqual(delivered);
  });

  it("no longer handles per-entity firehose facts", () => {
    expect(eventHandlers.BaggageStatusChanged).toBeUndefined();
    expect(eventHandlers.PassengerStatusChanged).toBeUndefined();
  });
});

describe("RC9 render/refetch economy", () => {
  beforeEach(() => { vi.useFakeTimers(); resetLiveProjectionGuards(); });
  afterEach(() => { vi.useRealTimers(); });

  it("an empty zone patch does not notify subscribers", () => {
    useBaggageStore.getState().setZones([{ zone_id: "induction-A", items: 1, status: "normal", throughput_per_hour: 1800, utilisation_pct: 1 }] as never);
    const listener = vi.fn();
    const unsubscribe = useBaggageStore.subscribe(listener);
    useBaggageStore.getState().updateZone("induction-A", {});
    useBaggageStore.getState().updateZone("no-such-zone", { items: 3 });
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("invalidates each query key at most once per window", () => {
    const spy = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    for (let i = 0; i < 50; i++) {
      eventHandlers.FlightStatusChanged({ flight_id: `F${i}`, new_status: "boarding" }, "2024-06-15T08:00:00", {} as never);
    }
    expect(spy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(RECONCILE_WINDOW_MS);
    const keys = spy.mock.calls.map(([arg]) => JSON.stringify((arg as { queryKey: string[] }).queryKey));
    expect(keys.filter(k => k === '["flights"]')).toHaveLength(1);
    expect(keys.filter(k => k === '["gates"]')).toHaveLength(1);
    expect(keys.filter(k => k === '["runways"]')).toHaveLength(1);
    reconcileLiveQueries("gates");
    vi.advanceTimersByTime(RECONCILE_WINDOW_MS);
    expect(spy.mock.calls.filter(([a]) => JSON.stringify((a as { queryKey: string[] }).queryKey) === '["gates"]')).toHaveLength(2);
    spy.mockRestore();
  });
});
