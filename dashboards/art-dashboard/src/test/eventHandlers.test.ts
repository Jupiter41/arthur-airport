import { describe, it, expect } from "vitest";
import { eventHandlers } from "../hooks/useWebSocket";

describe("eventHandlers registry", () => {
  const EXPECTED_EVENTS = [
    "SimClockTick",
    "FlightStatusChanged",
    "FlightGateAssigned",
    "FlightCancelled",
    "WeatherStateChanged",
    "BaggageStatusChanged",
    "BaggageFlagged",
    "PassengerStatusChanged",
    "IncidentCreated",
    "IncidentStatusChanged",
    "IncidentCascaded",
    "IncidentAlert",
  ];

  it("has handlers for all known event types", () => {
    for (const eventType of EXPECTED_EVENTS) {
      expect(
        eventHandlers[eventType],
        `missing handler for ${eventType}`,
      ).toBeTypeOf("function");
    }
  });

  it("every registered handler is a function", () => {
    for (const [key, handler] of Object.entries(eventHandlers)) {
      expect(handler, `handler for ${key} is not a function`).toBeTypeOf(
        "function",
      );
    }
  });

  it("supports extension by simple assignment", () => {
    const spy = () => {};
    eventHandlers["TestNewEvent"] = spy;
    expect(eventHandlers["TestNewEvent"]).toBe(spy);
    // Cleanup
    delete eventHandlers["TestNewEvent"];
  });
});
