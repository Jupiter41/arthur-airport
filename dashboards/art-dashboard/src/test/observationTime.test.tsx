import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ObservationTime } from "../components/ObservationTime";

afterEach(cleanup);
it("shows a complete UTC observation date across offset and day boundaries", () => {
  render(<ObservationTime value="2026-11-16T00:15:00+02:00" />);
  expect(screen.getByText("2026-11-15 22:15:00 UTC")).toHaveAttribute("datetime", "2026-11-15T22:15:00.000Z");
});
it.each([undefined, null, "", "invalid"])("does not substitute a current clock for absent evidence %s", value => {
  render(<ObservationTime value={value} />);
  expect(screen.getByText(/simulation time unavailable/)).toBeInTheDocument();
  expect(document.querySelector("time")).toBeNull();
});
it("treats legacy owner timestamps as UTC", () => {
  render(<ObservationTime value="2026-11-16T10:30:00" />);
  expect(screen.getByText("2026-11-16 10:30:00 UTC")).toBeInTheDocument();
});
