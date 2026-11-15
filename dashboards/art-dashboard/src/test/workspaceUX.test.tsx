import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { AirportHeatmap } from "../pages/PassengerFlow/AirportHeatmap";

afterEach(cleanup);
it("separates operational navigation from planning and system tools", () => {
  render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Flights" })).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Diagnostics" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Workspace" }), {
    target: { value: "Planning" },
  });
  expect(screen.getByRole("link", { name: "Experiments" })).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Flights" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Workspace" }), {
    target: { value: "System" },
  });
  expect(
    screen.getByRole("link", { name: "Incident lab" }),
  ).toBeInTheDocument();
});

it("does not invent healthy zones when terminal observations are absent", () => {
  const zone = {
    zone_id: "security-B",
    zone_type: "security",
    terminal: "B",
    density: 73,
    capacity: 100,
    load_pct: 73,
  };
  const select = vi.fn();
  render(
    <AirportHeatmap zones={[zone]} lockedZones={new Set()} onSelect={select} />,
  );
  expect(screen.queryByText("Terminal A")).not.toBeInTheDocument();
  expect(screen.queryByText("carousel-1")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /security-B/ }));
  expect(select).toHaveBeenCalledWith(zone);
});
