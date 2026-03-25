import { describe, it, expect, beforeEach } from "vitest";
import { useConnectionStore } from "../../stores/connectionStore";

describe("connectionStore", () => {
  beforeEach(() => {
    useConnectionStore.setState({
      apiConnected: null,
      wsConnected: false,
      lastApiError: null,
      lastWsError: null,
      wsLastMessageAt: null,
    });
  });

  it("setApiConnected sets connected true and clears error", () => {
    useConnectionStore.getState().setApiConnected(true);
    const s = useConnectionStore.getState();
    expect(s.apiConnected).toBe(true);
    expect(s.lastApiError).toBeNull();
  });

  it("setApiConnected sets connected false and records error", () => {
    useConnectionStore.getState().setApiConnected(false, "timeout");
    const s = useConnectionStore.getState();
    expect(s.apiConnected).toBe(false);
    expect(s.lastApiError).toBe("timeout");
  });

  it("setApiConnected defaults error message when not provided", () => {
    useConnectionStore.getState().setApiConnected(false);
    expect(useConnectionStore.getState().lastApiError).toBe("API unreachable");
  });

  it("setWsConnected tracks WS state", () => {
    useConnectionStore.getState().setWsConnected(true);
    expect(useConnectionStore.getState().wsConnected).toBe(true);
    expect(useConnectionStore.getState().lastWsError).toBeNull();
  });

  it("markWsMessage records timestamp", () => {
    useConnectionStore.getState().markWsMessage();
    expect(useConnectionStore.getState().wsLastMessageAt).toBeTruthy();
  });
});
