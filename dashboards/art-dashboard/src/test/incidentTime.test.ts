import { expect, it } from "vitest";
import { formatRelativeTime } from "../pages/IncidentConsole/utils";

it("uses only the supplied simulation clock, including UTC offsets", () => {
  expect(formatRelativeTime("2024-06-15T10:00:00", "2024-06-15T12:30:00+02:00")).toBe("30 sim-min ago");
  expect(formatRelativeTime("2024-06-15T10:00:00Z", "2024-06-15T11:01:00Z")).toBe("1h 1m ago (simulated)");
});
it("exposes missing clocks and future observations instead of inventing ages", () => {
  expect(formatRelativeTime("2024-06-15T10:00:00Z", null)).toBe("simulation age unavailable");
  expect(formatRelativeTime("invalid", "2024-06-15T10:00:00Z")).toBe("simulation age unavailable");
  expect(formatRelativeTime("2024-06-15T10:01:00Z", "2024-06-15T10:00:00Z")).toBe("start is ahead of source clock");
});

it("renders bare simulation timestamps as UTC in any browser timezone", async () => {
  const { formatSimTime } = await import("../pages/IncidentConsole/utils");
  expect(formatSimTime("2024-07-06T13:43:00")).toBe("13:43");
  expect(formatSimTime("2024-07-06T15:43:00+02:00")).toBe("13:43");
  expect(formatSimTime("invalid")).toBe("--:--");
});

it("keeps flight-board and overview movement times on the UTC clock", async () => {
  const { formatTime } = await import("../pages/FlightBoard/helpers");
  expect(formatTime("2024-07-06T13:43:00")).toBe("13:43");
  expect(formatTime("2024-07-06T15:43:00+02:00")).toBe("13:43");
});
