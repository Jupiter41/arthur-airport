import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WhatIfPage from "../pages/WhatIf/WhatIfPage";

const api = vi.hoisted(() => ({
  listScenarios: vi.fn(async () => ({ scenarios: [
    { id: "parent-1", name: "Synthetic parent", status: "completed", parent_scenario_id: null },
    { id: "child-1", name: "Synthetic child", status: "completed", parent_scenario_id: "parent-1" },
    { id: "pending-1", name: "Unfinished parent", status: "running", parent_scenario_id: null },
  ] })),
  causalGraph: vi.fn(async () => ({ nodes: [
    { id: "kpi-delay", type: "kpi", label: "avg_delay_minutes", mean: 12.34 },
  ], edges: [] })),
  listReplays: vi.fn(async () => ({ replays: [{
    id: "child-1", name: "Synthetic parent — shift +0m", status: "completed",
    results: { kpis: {
      avg_delay_minutes: { mean: 8.25 }, missed_connections: { mean: 3 },
      eu261_liability_eur: { mean: 1200 },
    } },
  }] })),
  counterfactualReport: vi.fn(async () => ({ children: [] })),
  replayScenario: vi.fn(async () => ({ scenario_id: "child-2" })),
}));

vi.mock("../hooks/useApi", () => ({ planningApi: api }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("What-if API contract", () => {
  it("renders real graph/replay responses and submits the report schema", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><WhatIfPage /></QueryClientProvider>);
    expect(await screen.findByText("Synthetic parent — shift +0m")).toBeInTheDocument();
    expect(await screen.findByText("12.34")).toBeInTheDocument();
    expect(screen.getByText("8.25")).toBeInTheDocument();
    expect(screen.getByText("1200")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Synthetic child/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Unfinished parent/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    await waitFor(() => expect(api.counterfactualReport).toHaveBeenCalledWith("parent-1", {
      base_interventions: [{ action: "open_security_lanes", sim_minute: 120,
        duration_minutes: 60, params: { lanes: 2 } }],
      shifts: [-60, -30, 0, 30, 60],
    }));
    client.clear();
  });
});
