import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { LegacySpatialRedirect, OperationalView } from "../components/OperationalView";

vi.mock("../pages/Airport3D/Airport3DPage", () => ({ default: ({ view }: { view: string }) => <p>Live 3D {view}</p> }));
afterEach(cleanup);
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
it.each(["airport", "passengers", "baggage"] as const)("defaults %s to 3D and switches to 2D at the same location", async view => {
  render(<MemoryRouter initialEntries={["/operations?terminal=B"]}><OperationalView view={view} title="Operations"><p>Existing 2D operations</p></OperationalView><Location /></MemoryRouter>);
  expect(await screen.findByText(`Live 3D ${view}`)).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "3D view" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(screen.getByRole("switch", { name: "3D view" }));
  expect(await screen.findByText("Existing 2D operations")).toBeInTheDocument();
  expect(screen.getByText("/operations?terminal=B&3d=off")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("switch", { name: "3D view" }));
  expect(await screen.findByText(`Live 3D ${view}`)).toBeInTheDocument();
});
it("retains an explicit 2D deep link on load", () => {
  render(<MemoryRouter initialEntries={["/passengers?3d=off"]}><OperationalView view="passengers" title="Passengers"><p>2D passenger map</p></OperationalView></MemoryRouter>);
  expect(screen.getByText("2D passenger map")).toBeInTheDocument();
});
it("redirects legacy 3D links to the matching operations page with terminal intact", async () => {
  render(<MemoryRouter initialEntries={["/airport-3d?view=baggage&terminal=C"]}><Routes><Route path="/airport-3d" element={<LegacySpatialRedirect />} /><Route path="/baggage" element={<Location />} /></Routes></MemoryRouter>);
  expect(await screen.findByText("/baggage?terminal=C&3d=on")).toBeInTheDocument();
});
