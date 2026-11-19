import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EffectiveSettings } from "../pages/Settings/EffectiveSettings";
import { passengersApi } from "../hooks/useApi";
import type { SettingsResponse } from "../pages/Settings/types";

vi.mock("../hooks/useApi", () => ({ passengersApi: { setLanes: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const effective: SettingsResponse["effective"] = {
  passenger: { status: "available", sim_time: "2024-06-15T12:00:00Z", values: { lanes_a: 8, lanes_b: 12, lanes_c: 8, mct_minutes: 45 } },
  baggage: { status: "available", sim_time: null, values: { screening_units: 6, sorting_capacity: 5400, dg_false_positive_rate: 0.003 } },
};
function setup(value = effective, canChange = true) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><EffectiveSettings effective={value} canChange={canChange} /></QueryClientProvider>);
}

it("keeps owner observations visible until an explicit owner command is confirmed and reobserved", async () => {
  vi.mocked(passengersApi.setLanes).mockRejectedValueOnce(new Error("response lost")).mockResolvedValueOnce({});
  setup();
  expect(screen.getByText("Sorting capacity: 5,400 bags/h")).toBeInTheDocument();
  expect(screen.queryByRole("spinbutton", { name: /Sorting/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton", { name: "Requested lanes — Terminal A" }), { target: { value: "3" } });
  const send = screen.getByRole("button", { name: "Send Terminal A lane command" });
  fireEvent.click(send);
  await screen.findByRole("alert");
  fireEvent.click(send);
  await screen.findByText(/Owner acknowledged/);
  expect(passengersApi.setLanes).toHaveBeenCalledTimes(2);
  const calls = vi.mocked(passengersApi.setLanes).mock.calls;
  expect(calls[0]).toEqual(["A", 3, expect.any(String)]);
  expect(calls[1][2]).toBe(calls[0][2]);
  expect(screen.getAllByText("8 lanes applied", { exact: true })).toHaveLength(2);
});

it("shows unknown owner values during outage and prevents commands without operator access", async () => {
  const view = setup(effective, false);
  expect(screen.getByRole("spinbutton", { name: "Requested lanes — Terminal A" })).toBeDisabled();
  view.unmount();
  setup({ passenger: { status: "unavailable", sim_time: null, values: null }, baggage: { status: "unavailable", sim_time: null, values: null } });
  await waitFor(() => expect(screen.getByText(/Effective lanes and MCT unknown/)).toBeInTheDocument());
  expect(screen.getByText(/Effective capacities unknown/)).toBeInTheDocument();
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
});
