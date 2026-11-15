"""The teaching runner fails closed and restores the lab after incomplete evidence."""

from copy import deepcopy
import json

import pytest

from scripts.teach_security_loop import choose_flights, run_lesson


class LabGateway:
    def __init__(self, eligible=True, receipt=True):
        self.calls = []
        self.settings = {"weather_lock": None, "runway_incursion_rate": .01, "baggage_fire_rate": .01,
                         "security_breach_rate": .01, "system_failure_rate": .01}
        self.decision = {"id": "p1", "status": "measured", "predicted": {"delta": -6},
                         "receipt": {"event_type": "CommandExecuted", "topic": "passengers.events"} if receipt else None,
                         "outcome": {"attribution": {"calibration_eligible": eligible, "control_count": 2}}}

    def api(self, path, method="GET", body=None):
        self.calls.append((path, method, deepcopy(body)))
        if method != "GET":
            if path.endswith("/apply"):
                assert body["request_approval"] is True
                return {"proposal_id": "p1"}
            return {"event_type": "CommandExecuted", "receipt": {"command_type": "OpenSecurityLane"}}
        if path == "/control":
            return {"enabled": False}
        if path == "/sim/status":
            return {"sim_time": "2026-01-01T06:00:00Z", "speed_multiplier": 10, "paused": True}
        if path == "/sim/settings":
            return deepcopy(self.settings)
        if path == "/analysis/autonomous":
            return {"autonomous": {"enabled": False}}
        if path == "/analysis/approvals?all=true":
            return {"approvals": []}
        if path == "/passengers/flow/summary":
            return {"security": {t: {"lanes_open": 8} for t in "ABC"}}
        if path == "/flights?limit=500":
            return {"flights": [{"id": t, "direction": "departure", "gate_id": f"{t}01", "scheduled_time": "2026-01-01T10:00:00Z"} for t in "ABC"]}
        if path == "/analysis/recommendations":
            return {"recommendations": [{"id": "r1", "action_type": "open_security_lane", "executable": True,
                                          "parameters": {"terminal": "A", "new_lane_count": 2}}]}
        if path == "/analysis/decisions/p1":
            return deepcopy(self.decision)
        raise AssertionError((path, method, body))


def test_success_exports_actual_gateway_evidence_and_restores_every_lane(tmp_path):
    gateway = LabGateway()
    target = tmp_path / "lesson.json"
    report = run_lesson(gateway, target, 1)
    assert report["verification_status"] == "complete_observational_example"
    assert report["empirical_accuracy"] == "unvalidated"
    assert report["restoration_errors"] == []
    assert json.loads(target.read_text())["decision"] == gateway.decision
    for terminal in "ABC":
        assert (f"/passengers/flow/security/{terminal}/lanes", "POST", {"lanes_open": 8}) in gateway.calls
    assert gateway.calls[-1] == ("/sim/pause", "POST", {})


@pytest.mark.parametrize("missing", ["baseline", "receipt"])
def test_incomplete_evidence_cannot_report_success_and_still_restores_settings(tmp_path, missing):
    gateway = LabGateway(eligible=missing != "baseline", receipt=missing != "receipt")
    with pytest.raises(RuntimeError):
        run_lesson(gateway, tmp_path / "lesson.json", 1)
    assert ("/sim/settings", "PATCH", gateway.settings) in gateway.calls
    assert gateway.calls[-1] == ("/sim/pause", "POST", {})
    if missing == "baseline":
        report = json.loads((tmp_path / "lesson.json").read_text())
        assert report["verification_status"] == "incomplete_attribution"


def test_future_flights_are_required_to_protect_the_measurement_window():
    with pytest.raises(ValueError, match="90 sim-minutes"):
        choose_flights([{"id": "short", "direction": "departure", "gate_id": "A01",
                         "scheduled_time": "2026-01-01T06:15:00Z"}], "2026-01-01T06:00:00Z")
