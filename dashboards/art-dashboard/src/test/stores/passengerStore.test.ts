import { describe, it, expect, beforeEach } from "vitest";
import { usePassengerStore } from "../../stores/passengerStore";
import type { ZoneDensity, ConnectionAtRisk } from "../../types";

const makeZone = (overrides: Partial<ZoneDensity> = {}): ZoneDensity =>
  ({
    zone_id: "security-A",
    zone_type: "security",
    terminal: "A",
    density: 80,
    capacity: 200,
    load_pct: 40,
    ...overrides,
  }) as ZoneDensity;

describe("passengerStore", () => {
  beforeEach(() => {
    usePassengerStore.setState({
      summary: null,
      zones: [],
      connectionsAtRisk: [],
    });
  });

  it("setZones replaces zone list", () => {
    usePassengerStore
      .getState()
      .setZones([makeZone(), makeZone({ zone_id: "security-B" })]);
    expect(usePassengerStore.getState().zones).toHaveLength(2);
  });

  it("updateZoneDensity patches density and load_pct for matching zone", () => {
    usePassengerStore
      .getState()
      .setZones([makeZone(), makeZone({ zone_id: "gate-A1" })]);
    usePassengerStore.getState().updateZoneDensity("security-A", 120, 60);
    const z = usePassengerStore
      .getState()
      .zones.find((z) => z.zone_id === "security-A")!;
    expect(z.density).toBe(120);
    expect(z.load_pct).toBe(60);
    // Other zone untouched
    expect(
      usePassengerStore.getState().zones.find((z) => z.zone_id === "gate-A1")!
        .density,
    ).toBe(80);
  });

  it("setSummary sets summary", () => {
    const sum = {
      total_in_airport: 3000,
      connections_at_risk: 5,
      connections_missed: 1,
    };
    usePassengerStore.getState().setSummary(sum as never);
    expect(usePassengerStore.getState().summary).toBeTruthy();
  });

  it("setConnectionsAtRisk replaces list", () => {
    const c = [
      { passenger_id: "p-001", risk_level: "at_risk" },
    ] as ConnectionAtRisk[];
    usePassengerStore.getState().setConnectionsAtRisk(c);
    expect(usePassengerStore.getState().connectionsAtRisk).toHaveLength(1);
  });
});
