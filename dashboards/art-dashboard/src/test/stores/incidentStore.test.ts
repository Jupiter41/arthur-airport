import { describe, it, expect, beforeEach } from "vitest";
import { useIncidentStore } from "../../stores/incidentStore";
import type { Incident, IncidentAlert } from "../../types";

const makeIncident = (overrides: Partial<Incident> = {}): Incident =>
  ({
    id: "inc-001",
    type: "runway_incursion",
    title: "Runway incursion 09L",
    severity: "critical",
    status: "active",
    location: "runway-09L",
    started_at: "2025-01-01T08:00:00Z",
    protocols: ["RUNWAY_STOP"],
    cascade_depth: 1,
    cascade_tree: null,
    ...overrides,
  }) as Incident;

describe("incidentStore", () => {
  beforeEach(() => {
    useIncidentStore.setState({ incidents: {}, alerts: [] });
  });

  it("setIncidents indexes by id", () => {
    useIncidentStore.getState().setIncidents([
      makeIncident({ id: "inc-001" }),
      makeIncident({ id: "inc-002", type: "baggage_fire" }),
    ]);
    expect(Object.keys(useIncidentStore.getState().incidents)).toHaveLength(2);
  });

  it("setIncidents normalizes protocol → protocols", () => {
    const raw = { ...makeIncident(), protocols: undefined, protocol: "GROUND_STOP" };
    useIncidentStore.getState().setIncidents([raw as unknown as Incident]);
    const inc = useIncidentStore.getState().incidents["inc-001"];
    expect(inc.protocols).toEqual(["GROUND_STOP"]);
  });

  it("upsertIncident adds or replaces", () => {
    useIncidentStore.getState().setIncidents([makeIncident()]);
    useIncidentStore.getState().upsertIncident(makeIncident({ id: "inc-001", status: "contained" }));
    expect(useIncidentStore.getState().incidents["inc-001"].status).toBe("contained");
  });

  it("updateIncidentStatus changes status", () => {
    useIncidentStore.getState().setIncidents([makeIncident()]);
    useIncidentStore.getState().updateIncidentStatus("inc-001", "resolved");
    expect(useIncidentStore.getState().incidents["inc-001"].status).toBe("resolved");
  });

  it("updateIncidentStatus is a no-op for unknown id", () => {
    useIncidentStore.getState().setIncidents([makeIncident()]);
    useIncidentStore.getState().updateIncidentStatus("unknown", "resolved");
    expect(useIncidentStore.getState().incidents["inc-001"].status).toBe("active");
  });

  it("addAlert prepends and caps at 200", () => {
    const alert: IncidentAlert = {
      id: "alert-001",
      sim_time: "2025-01-01T08:00:00Z",
      severity: "critical",
      message: "Runway closed",
      incident_id: "inc-001",
    };
    useIncidentStore.getState().addAlert(alert);
    expect(useIncidentStore.getState().alerts).toHaveLength(1);
    expect(useIncidentStore.getState().alerts[0].id).toBe("alert-001");
  });

  it("addAlert caps list at MAX_ALERTS (200)", () => {
    const existing = Array.from({ length: 200 }, (_, i) => ({
      id: `a-${i}`,
      sim_time: "",
      severity: "low" as const,
      message: "",
      incident_id: "",
    }));
    useIncidentStore.getState().setAlerts(existing);
    useIncidentStore.getState().addAlert({
      id: "a-new",
      sim_time: "",
      severity: "critical",
      message: "new",
      incident_id: "",
    });
    const alerts = useIncidentStore.getState().alerts;
    expect(alerts).toHaveLength(200); // capped
    expect(alerts[0].id).toBe("a-new"); // newest first
  });

  it("setAlerts replaces entire list", () => {
    useIncidentStore.getState().setAlerts([
      { id: "a1", sim_time: "", severity: "medium", message: "test", incident_id: "" },
    ] as IncidentAlert[]);
    expect(useIncidentStore.getState().alerts).toHaveLength(1);
  });
});
