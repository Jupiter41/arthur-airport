import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { FIDSPanel } from "../pages/FlightBoard/FIDSPanel";
import type { Flight } from "../types";

afterEach(cleanup);
const flight = (id: string, scheduled_time: string) =>
  ({
    id,
    flight_number: id,
    scheduled_time,
    origin_iata: "ART",
    destination_iata: "ZZZ",
    direction: "departure",
    delay_minutes: 0,
    status: "scheduled",
  }) as Flight;
function Location() {
  const l = useLocation();
  return <output>{l.search}</output>;
}
it("retains chronological order when another flight updates and exposes keyboard sorting", () => {
  const flights = [
    flight("AX101", "2026-01-01T11:00:00+01:00"),
    flight("AX102", "2026-01-01T10:30:00Z"),
  ];
  render(
    <MemoryRouter initialEntries={["/flights?terminal=B&flight=AX101"]}>
      <FIDSPanel
        flights={flights}
        direction="all"
        flashIds={new Set(["AX102"])}
        onSelect={() => undefined}
      />
      <Location />
    </MemoryRouter>,
  );
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("AX101");
  fireEvent.click(
    screen.getByRole("button", { name: /Scheduled \/ estimated/ }),
  );
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("AX102");
  expect(
    screen.getByText(/terminal=B&flight=AX101&sort=scheduled_time&order=desc/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("columnheader", { name: /Scheduled/ }),
  ).toHaveAttribute("aria-sort", "descending");
  expect(
    screen.getByRole("button", { name: "Inspect AX101" }),
  ).toBeInTheDocument();
});
