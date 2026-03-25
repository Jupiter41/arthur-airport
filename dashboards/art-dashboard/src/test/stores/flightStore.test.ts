import { describe, it, expect, beforeEach } from "vitest";
import { useFlightStore } from "../../stores/flightStore";
import type { Flight } from "../../types";

const makeFlight = (overrides: Partial<Flight> = {}): Flight =>
  ({
    id: "fl-001",
    flight_number: "ART101",
    airline_code: "AR",
    aircraft_type: "A320",
    registration: "N-ART1",
    direction: "departure",
    origin_iata: "ART",
    destination_iata: "JFK",
    terminal: "A",
    gate_id: "A-01",
    runway_id: null,
    status: "scheduled",
    scheduled_time: "2025-01-01T08:00:00Z",
    estimated_time: null,
    actual_time: null,
    delay_minutes: 0,
    pax_count: 150,
    pax_boarded: 0,
    baggage_count: 200,
    baggage_loaded: 0,
    ...overrides,
  }) as Flight;

describe("flightStore", () => {
  beforeEach(() => {
    useFlightStore.setState({
      flights: {},
      runways: [],
      gates: [],
      flashIds: new Set(),
    });
  });

  it("setFlights indexes by id", () => {
    const list = [
      makeFlight({ id: "fl-001" }),
      makeFlight({ id: "fl-002", flight_number: "ART102" }),
    ];
    useFlightStore.getState().setFlights(list);
    const flights = useFlightStore.getState().flights;
    expect(Object.keys(flights)).toHaveLength(2);
    expect(flights["fl-001"].flight_number).toBe("ART101");
    expect(flights["fl-002"].flight_number).toBe("ART102");
  });

  it("upsertFlight adds or replaces a flight", () => {
    useFlightStore.getState().setFlights([makeFlight()]);
    useFlightStore
      .getState()
      .upsertFlight(makeFlight({ id: "fl-001", status: "boarding" }));
    expect(useFlightStore.getState().flights["fl-001"].status).toBe("boarding");
  });

  it("updateFlightStatus updates status and optional delay", () => {
    useFlightStore.getState().setFlights([makeFlight()]);
    useFlightStore.getState().updateFlightStatus("fl-001", "delayed", 15);
    const f = useFlightStore.getState().flights["fl-001"];
    expect(f.status).toBe("delayed");
    expect(f.delay_minutes).toBe(15);
  });

  it("updateFlightStatus keeps existing delay when none provided", () => {
    useFlightStore.getState().setFlights([makeFlight({ delay_minutes: 10 })]);
    useFlightStore.getState().updateFlightStatus("fl-001", "boarding");
    expect(useFlightStore.getState().flights["fl-001"].delay_minutes).toBe(10);
  });

  it("updateFlightStatus is a no-op for unknown flight", () => {
    useFlightStore.getState().setFlights([makeFlight()]);
    useFlightStore.getState().updateFlightStatus("unknown", "boarding");
    expect(Object.keys(useFlightStore.getState().flights)).toHaveLength(1);
  });

  it("updateFlightGate changes gate_id", () => {
    useFlightStore.getState().setFlights([makeFlight()]);
    useFlightStore.getState().updateFlightGate("fl-001", "B-05");
    expect(useFlightStore.getState().flights["fl-001"].gate_id).toBe("B-05");
  });

  it("cancelFlight sets status to cancelled", () => {
    useFlightStore.getState().setFlights([makeFlight()]);
    useFlightStore.getState().cancelFlight("fl-001");
    expect(useFlightStore.getState().flights["fl-001"].status).toBe(
      "cancelled",
    );
  });

  it("flashRow and clearFlash manage flashIds set", () => {
    useFlightStore.getState().flashRow("fl-001");
    expect(useFlightStore.getState().flashIds.has("fl-001")).toBe(true);

    useFlightStore.getState().clearFlash("fl-001");
    expect(useFlightStore.getState().flashIds.has("fl-001")).toBe(false);
  });

  it("setRunways replaces runway list", () => {
    useFlightStore
      .getState()
      .setRunways([
        {
          runway_id: "09L",
          status: "open",
          arrivals_queued: 0,
          departures_queued: 2,
        },
      ] as never[]);
    expect(useFlightStore.getState().runways).toHaveLength(1);
  });

  it("setGates replaces gate list", () => {
    useFlightStore
      .getState()
      .setGates([
        { gate_id: "A-01", terminal: "A", status: "available" },
      ] as never[]);
    expect(useFlightStore.getState().gates).toHaveLength(1);
  });
});
