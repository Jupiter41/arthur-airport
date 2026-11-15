import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SceneViewport } from "../pages/Airport3D/SceneViewport";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it("provides operational links when the device cannot create a WebGL renderer", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  render(<MemoryRouter><SceneViewport data={{ flights: [], gates: [], runways: [], vehicles: [], zones: [] }} options={{ view: "airport", terminal: "A", quality: "low" }} selectedId={null} onSelect={() => {}} preset="overview" cameraRevision={0} /></MemoryRouter>);
  expect(await screen.findByRole("alert")).toHaveTextContent("3D rendering is unavailable on this device");
  expect(screen.getByRole("link", { name: "Passenger flow →" })).toHaveAttribute("href", "/passengers?3d=off");
  expect(screen.queryByTestId("scene-host")).not.toBeInTheDocument();
});
