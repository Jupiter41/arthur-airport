import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SimClock } from "../components/SimClock";
import { useSimStore } from "../stores/simStore";

afterEach(cleanup);
it.each(["2024-07-06T13:43:00", "2024-07-06T15:43:00+02:00"])("keeps the shell clock in simulated UTC: %s", sim_time => {
  useSimStore.setState(s => ({ status: {...s.status, sim_time, day_number: 22, tick_count: 1} }));
  render(<SimClock />);
  expect(screen.getByText("Day 22 · 13:43 UTC")).toBeInTheDocument();
});
it("does not show a fabricated time for an invalid source clock", () => {
  useSimStore.setState(s => ({ status: {...s.status, sim_time: "invalid", tick_count: 1} }));
  render(<SimClock />);
  expect(screen.getByText("Awaiting source clock")).toBeInTheDocument();
});
