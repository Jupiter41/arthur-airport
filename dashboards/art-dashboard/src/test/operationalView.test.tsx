import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import {
  LegacySpatialRedirect,
  OperationalView,
} from "../components/OperationalView";

vi.mock("../pages/Airport3D/Airport3DPage", () => ({
  default: ({ view }: { view: string }) => <p>Live 3D {view}</p>,
}));
afterEach(cleanup);
function Location() {
  const location = useLocation();
  return (
    <output>
      {location.pathname}
      {location.search}
    </output>
  );
}
it.each(["airport", "passengers", "baggage"] as const)(
  "defaults %s to Board and preserves scope/selection in 3D",
  async (view) => {
    render(
      <MemoryRouter initialEntries={["/operations?terminal=B&entity=selected"]}>
        <OperationalView view={view} title="Operations">
          <p>Existing 2D operations</p>
        </OperationalView>
        <Location />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Existing 2D operations")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "3D" }));
    expect(await screen.findByText(`Live 3D ${view}`)).toBeInTheDocument();
    expect(
      screen.getByText("/operations?terminal=B&entity=selected&mode=3d"),
    ).toBeInTheDocument();
    expect(screen.getByText("Existing 2D operations")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(screen.queryByText(`Live 3D ${view}`)).not.toBeInTheDocument();
  },
);
it("retains an explicit 2D deep link on load", () => {
  render(
    <MemoryRouter initialEntries={["/passengers?3d=off"]}>
      <OperationalView view="passengers" title="Passengers">
        <p>2D passenger map</p>
      </OperationalView>
    </MemoryRouter>,
  );
  expect(screen.getByText("2D passenger map")).toBeInTheDocument();
});
it("redirects legacy 3D links to the matching operations page with terminal intact", async () => {
  render(
    <MemoryRouter initialEntries={["/airport-3d?view=baggage&terminal=C"]}>
      <Routes>
        <Route path="/airport-3d" element={<LegacySpatialRedirect />} />
        <Route path="/baggage" element={<Location />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("/baggage?terminal=C&3d=on"),
  ).toBeInTheDocument();
});
