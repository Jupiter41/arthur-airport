import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { DecisionTimeline } from "../pages/Decisions/DecisionTimeline";
import { DecisionWorkspace } from "../pages/Decisions/DecisionWorkspace";
import type { DecisionTimeline as Timeline } from "../types/decisions";

const api = vi.hoisted(() => ({ applyRecommendation: vi.fn(), approveProposal: vi.fn(), rejectProposal: vi.fn(), decisions: vi.fn(), decision: vi.fn() }));
const access = vi.hoisted(() => ({ role: "approver", controlling: true }));
vi.mock("../hooks/useApi", () => ({ analysisApi: api }));
vi.mock("../hooks/auth", () => ({ useAccess: () => access }));
afterEach(() => { cleanup(); vi.resetAllMocks(); access.role = "approver"; });

function fixture(): Timeline {
  const at = "2026-01-01T12:00:00Z";
  const recommendation = { id: "r1", bottleneck_id: "bn1", action_type: "open_security_lane", description: "Open Terminal A lane", expected_impact: "Projected wait reduction", cost: "One staff member", confidence_score: .8, expiry_sim_time: at, priority_rank: 1, impact_value: 100, cost_value: 25, priority_score: 3.2, calibration_samples: 0, parameters: { terminal: "A", new_lane_count: 5 }, executable: true, applied: false, applied_at: null };
  return { id: "p1", bottleneck_id: "bn1", bottleneck: { id: "bn1", type: "security_queue", severity: "critical", zone: "Terminal A", root_cause: "Security queue congestion", estimated_duration_minutes: 30, affected_entity_count: 300, detected_at: at, metrics: {}, resolved_at: null }, recommendation, alternatives: [recommendation], description: "Open Terminal A lane", status: "measured", proposal_status: "executed", proposal_id: "p1", action_type: "open_security_lane", parameters: {}, stages: ["detected", "predicted", "ranked", "approved", "dispatched", "executed", "measured"].map(stage => ({ stage, at, details: {} })), predicted: { metric: "security_wait_minutes", delta: -6 }, outcome: { measurable: true, attribution: { method: "difference_in_differences", calibration_eligible: true, causal_claim: false, metric: "security_wait_minutes", treated_change: -10, attributed_effect: -8, control_count: 2 } }, receipt: { event_type: "CommandExecuted", topic: "passengers.events", sim_time: at, payload: { command_id: "p1" } }, dispatch_attempts: 1, failure_reason: null, effect_model_version: "effects-v1", context_available: true, financial_signals: {}, updated_at: at, action_available: false };
}
function renderPage(node: React.ReactNode, path = "/decisions") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{node}</MemoryRouter></QueryClientProvider>);
  return { ...result, client };
}

describe("Decision timeline", () => {
  it("separates prediction, observation, attribution and honest validation limits", () => {
    const { client } = renderPage(<DecisionTimeline decision={fixture()} />);
    expect(screen.getByText("-6.00")).toBeInTheDocument();
    expect(screen.getByText("-10.00")).toBeInTheDocument();
    expect(screen.getByText("-8.00")).toBeInTheDocument();
    expect(screen.getByText(/fewer than 20 samples/)).toBeInTheDocument();
    expect(screen.getByText(/passengers.events/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "Recorded stage" }), { target: { value: "0" } });
    expect(screen.queryByRole("region", { name: "Measured outcome" })).not.toBeInTheDocument();
    expect(screen.queryByText(/passengers.events/)).not.toBeInTheDocument();
    expect(api.applyRecommendation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Return to latest" }));
    expect(screen.getByText("-8.00")).toBeInTheDocument();
    client.clear();
  });
  it("queues approval without claiming execution and disables mutations during history playback", async () => {
    const pending = fixture();
    pending.status = pending.proposal_status = "pending"; pending.receipt = null; pending.outcome = null;
    pending.stages = pending.stages.slice(0, 3);
    api.approveProposal.mockResolvedValue({ status: "dispatched", applied: false });
    const { client } = renderPage(<DecisionTimeline decision={pending} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve and dispatch" }));
    await waitFor(() => expect(api.approveProposal).toHaveBeenCalledWith("p1"));
    expect(screen.queryByText("Owner confirmed execution")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    expect(screen.queryByRole("button", { name: "Approve and dispatch" })).not.toBeInTheDocument();
    client.clear();
  });
  it("keeps viewer actions disabled and reports failures", async () => {
    const pending = fixture(); pending.status = pending.proposal_status = "pending"; pending.stages = []; pending.outcome = null;
    access.role = "viewer";
    const { client } = renderPage(<DecisionTimeline decision={pending} />);
    expect(screen.getByRole("button", { name: "Approve and dispatch" })).toBeDisabled();
    expect(api.approveProposal).not.toHaveBeenCalled();
    client.clear();
  });
  it("does not display a pre/post observation as an attributed causal improvement", () => {
    const decision = fixture(); decision.outcome!.attribution!.method = "pre_post"; decision.outcome!.attribution!.calibration_eligible = false;
    const { client } = renderPage(<DecisionTimeline decision={decision} />);
    expect(screen.getByText("Unattributed pre/post change")).toBeInTheDocument();
    expect(screen.getByText(/Excluded from calibration/)).toBeInTheDocument();
    client.clear();
  });
});

describe("Durable decision browsing", () => {
  it("loads deep-linked history even when it is not on the current list page", async () => {
    api.decisions.mockResolvedValue({ decisions: [], total: 0, limit: 25, offset: 0 });
    api.decision.mockResolvedValue(fixture());
    const { client } = renderPage(<DecisionWorkspace />, "/decisions?decision=p1");
    expect(await screen.findByText("Open Terminal A lane")).toBeInTheDocument();
    expect(api.decision).toHaveBeenCalledWith("p1");
    client.clear();
  });
  it("distinguishes unavailable history from an empty decision log", async () => {
    api.decisions.mockRejectedValue(new Error("offline"));
    const { client } = renderPage(<DecisionWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Decision history unavailable");
    expect(screen.queryByText(/No decisions recorded yet/)).not.toBeInTheDocument();
    client.clear();
  });
});
