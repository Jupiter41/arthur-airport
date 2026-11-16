import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { eventHandlers } from "../hooks/useWebSocket";
import { useIncidentStore } from "../stores/incidentStore";
import { queryClient } from "../queryClient";
import type { KafkaEvent } from "../types";

const at = "2024-06-18T02:00:00Z";
const send = (type: string, payload: Record<string, unknown>) =>
  eventHandlers[type](payload, at, {event_type:type,payload,sim_time:at} as KafkaEvent);
beforeEach(() => useIncidentStore.setState({incidents:{},alerts:[]}));
afterEach(() => {vi.restoreAllMocks();queryClient.clear();});

it("normalizes the owner's incident_id and creation time before status updates", () => {
  send("IncidentCreated", {incident_id:"synthetic-child",type:"security_breach",severity:"high",location:"terminal-B"});
  expect(Object.keys(useIncidentStore.getState().incidents)).toEqual(["synthetic-child"]);
  expect(useIncidentStore.getState().incidents["synthetic-child"]).toMatchObject({
    id:"synthetic-child",started_at:at,observed_at:at,status:"active",
  });
  send("IncidentStatusChanged", {incident_id:"synthetic-child",new_status:"contained"});
  expect(useIncidentStore.getState().incidents["synthetic-child"].status).toBe("contained");
});
it("reconciles cascade relationship facts without inserting partial incident rows", async () => {
  vi.useFakeTimers();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  send("IncidentCascaded", {parent_incident_id:"parent",child_incident_id:"child",cascade_type:"zone_lockdown"});
  vi.advanceTimersByTime(1000); // RC9: invalidations are throttled per key
  vi.useRealTimers();
  expect(useIncidentStore.getState().incidents).toEqual({});
  expect(invalidate).toHaveBeenCalledWith({queryKey:["incidents"]});
});
