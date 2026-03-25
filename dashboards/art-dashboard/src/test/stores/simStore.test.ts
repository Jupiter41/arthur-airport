import { describe, it, expect, beforeEach } from "vitest";
import { useSimStore } from "../../stores/simStore";

describe("simStore", () => {
  beforeEach(() => {
    useSimStore.setState({
      status: {
        running: false,
        paused: false,
        speed_multiplier: 60,
        sim_time: "2025-01-01T06:00:00Z",
        day_number: 1,
        tick_count: 0,
      },
    });
  });

  it("updateFromTick advances sim_time and tick_count", () => {
    useSimStore.getState().updateFromTick("2025-01-01T06:01:00Z");
    const s = useSimStore.getState().status;
    expect(s.sim_time).toBe("2025-01-01T06:01:00Z");
    expect(s.tick_count).toBe(1);
  });

  it("updateFromTick increments tick_count cumulatively", () => {
    useSimStore.getState().updateFromTick("2025-01-01T06:01:00Z");
    useSimStore.getState().updateFromTick("2025-01-01T06:02:00Z");
    expect(useSimStore.getState().status.tick_count).toBe(2);
  });

  it("setPaused toggles running/paused", () => {
    useSimStore.getState().setPaused(true);
    const s = useSimStore.getState().status;
    expect(s.paused).toBe(true);
    expect(s.running).toBe(false);
  });

  it("setSpeed updates speed_multiplier", () => {
    useSimStore.getState().setSpeed(120);
    expect(useSimStore.getState().status.speed_multiplier).toBe(120);
  });

  it("setStatus replaces entire status", () => {
    const next = {
      running: true,
      paused: false,
      speed_multiplier: 120,
      sim_time: "2025-06-01T12:00:00Z",
      day_number: 5,
      tick_count: 500,
    };
    useSimStore.getState().setStatus(next);
    expect(useSimStore.getState().status).toEqual(next);
  });
});
