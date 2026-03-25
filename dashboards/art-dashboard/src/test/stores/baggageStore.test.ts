import { describe, it, expect, beforeEach } from "vitest";
import { useBaggageStore } from "../../stores/baggageStore";
import type { BaggageZone, FlaggedBaggage } from "../../types";

const makeZone = (overrides: Partial<BaggageZone> = {}): BaggageZone =>
  ({
    zone_id: "induction-A",
    zone_type: "induction",
    status: "active",
    items: 50,
    capacity: 100,
    utilisation_pct: 50,
    throughput_per_hour: 200,
    ...overrides,
  }) as BaggageZone;

describe("baggageStore", () => {
  beforeEach(() => {
    useBaggageStore.setState({ summary: null, zones: [], flagged: [] });
  });

  it("setZones replaces zone list", () => {
    useBaggageStore
      .getState()
      .setZones([makeZone(), makeZone({ zone_id: "induction-B" })]);
    expect(useBaggageStore.getState().zones).toHaveLength(2);
  });

  it("updateZone patches a single zone by id", () => {
    useBaggageStore
      .getState()
      .setZones([makeZone(), makeZone({ zone_id: "induction-B" })]);
    useBaggageStore.getState().updateZone("induction-A", { items: 80 });
    const z = useBaggageStore
      .getState()
      .zones.find((z) => z.zone_id === "induction-A")!;
    expect(z.items).toBe(80);
    // Other zone untouched
    expect(
      useBaggageStore.getState().zones.find((z) => z.zone_id === "induction-B")!
        .items,
    ).toBe(50);
  });

  it("setSummary sets summary", () => {
    const sum = {
      total_in_system: 500,
      by_status: { loaded: 200 },
      flagged_count: 3,
      loaded_count: 200,
    };
    useBaggageStore.getState().setSummary(sum);
    expect(useBaggageStore.getState().summary).toEqual(sum);
  });

  it("setFlagged replaces flagged list", () => {
    const f: FlaggedBaggage[] = [
      {
        id: "BAG-001",
        tag: "BAG-001",
        flag_reason: "overweight",
        dg_class: null,
        passenger_name: "John Doe",
        flight_number: "ART-100",
        current_zone: "screening-unit-1",
        review_status: "pending",
      },
    ];
    useBaggageStore.getState().setFlagged(f);
    expect(useBaggageStore.getState().flagged).toHaveLength(1);
  });

  it("addFlagged prepends to flagged list", () => {
    const base: FlaggedBaggage = {
      id: "BAG-001",
      tag: "BAG-001",
      flag_reason: "overweight",
      dg_class: null,
      passenger_name: "Jane Doe",
      flight_number: "ART-200",
      current_zone: "screening-unit-2",
      review_status: "pending",
    };
    const f1: FlaggedBaggage = { ...base, id: "BAG-001", tag: "BAG-001" };
    const f2: FlaggedBaggage = { ...base, id: "BAG-002", tag: "BAG-002" };
    useBaggageStore.getState().setFlagged([f1]);
    useBaggageStore.getState().addFlagged(f2);
    const flagged = useBaggageStore.getState().flagged;
    expect(flagged).toHaveLength(2);
    expect(flagged[0].tag).toBe("BAG-002"); // prepended
  });
});
