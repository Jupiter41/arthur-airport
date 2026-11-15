import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Airport3DPage from "../pages/Airport3D/Airport3DPage";

const state = vi.hoisted(() => ({ unavailable: [] as string[],
  data: { flights: [], gates: [], runways: [], vehicles: [], zones: [{ zone_id: "induction-A", status: "active", items: 2, utilisation_pct: 10, throughput_per_hour: 600 }], passenger: { security: { A: { queue_length: 73, wait_minutes: 14.5, lanes_open: 3 }, B: { queue_length: 5, wait_minutes: 1, lanes_open: 4 } } } } }));
const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));
vi.mock("../pages/Airport3D/useSceneData", () => ({ useSceneData: () => ({ ...state, loading: false, refresh: vi.fn() }) }));
vi.mock("../pages/Airport3D/SceneViewport", () => ({ SceneViewport: () => <div>3D canvas mocked in component tests</div> }));
vi.mock("../hooks/useApi", () => ({ baggageApi: api }));
afterEach(() => { cleanup(); vi.resetAllMocks(); state.unavailable = []; });
function page(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Airport3DPage /></MemoryRouter></QueryClientProvider>);
  return client;
}
describe("3D page interaction", () => {
  it("opens a passenger deep link and scopes observed lane metrics by terminal", () => {
    const client = page("/airport-3d?view=passengers&terminal=A");
    expect(screen.getByText("73")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Terminal A security/ }));
    expect(screen.getByRole("heading", { name: "Terminal A security" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Terminal"), { target: { value: "B" } });
    expect(screen.getByRole("button", { name: /Terminal B security/ })).toHaveTextContent("4 lanes open");
    expect(screen.queryByRole("heading", { name: "Terminal A security" })).not.toBeInTheDocument();
    client.clear();
  });
  it("reads actual bag records and scan history rather than assigning representative meshes fake identities", async () => {
    api.list.mockResolvedValue({ total: 1, items: [{ id: "bag-1", tag: "TEST-001", status: "inducted" }] });
    api.get.mockResolvedValue({ id: "bag-1", tag: "TEST-001", status: "inducted", last_scan_zone: "induction-A", scan_history: [{ zone: "induction-A", status: "inducted", at: "2026-01-01T12:00:00Z" }] });
    const client = page("/airport-3d?view=baggage");
    fireEvent.click(screen.getByRole("button", { name: /induction-A/ }));
    fireEvent.click(await screen.findByRole("button", { name: /TEST-001/ }));
    expect(await screen.findByText("2026-01-01T12:00:00Z")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ zone: "induction-A", limit: "50" });
    expect(api.get).toHaveBeenCalledWith("bag-1"); client.clear();
  });
  it("shows stale-source notices and retains access to the 2D pages", () => {
    state.unavailable = ["Passengers"];
    const client = page("/airport-3d?view=passengers");
    expect(screen.getByRole("alert")).toHaveTextContent("Unavailable or stale: Passengers");
    expect(screen.getByRole("link", { name: "Passenger flow ↗" })).toHaveAttribute("href", "/passengers");
    expect(screen.queryByRole("checkbox", { name: "Illustrative motion" })).not.toBeInTheDocument();
    expect(screen.getByText(/no independent 3D simulation/)).toBeInTheDocument(); client.clear();
  });
});
