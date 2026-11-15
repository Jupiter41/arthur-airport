"""Ground-vehicle trip facts exposed for sim-time visual interpolation."""

from datetime import datetime, timedelta

from tests.conftest import import_service_module

gv = import_service_module("flight", "services.ground_vehicles")

T0 = datetime(2026, 1, 1, 12, 0)


def _pool():
    pool = gv.GroundVehiclePool()
    pool.initialize_fleet()
    pool.set_gate_positions({"A01": {"position_x": 160.0, "position_y": 150.0}})
    return pool


def test_dispatch_records_origin_target_and_timestamps():
    pool = _pool()
    vehicle, transit = pool.request_vehicle("fueling", "A01", "f1", T0)
    data = vehicle.to_dict()
    assert (data["origin_x"], data["origin_y"]) == (gv.DEPOT_POSITION["x"], gv.DEPOT_POSITION["y"])
    assert (data["target_x"], data["target_y"]) == (160.0, 150.0)
    assert data["dispatched_at"] == T0.isoformat()
    assert data["arrives_at"] == (T0 + timedelta(minutes=transit)).isoformat()


def test_arrival_and_return_close_and_open_trips():
    pool = _pool()
    vehicle, transit = pool.request_vehicle("fueling", "A01", "f1", T0)
    pool.advance(T0 + timedelta(minutes=transit))
    assert vehicle.status == "at_gate" and vehicle.to_dict()["origin_x"] is None
    released, back = pool.release_vehicle(vehicle.id, T0 + timedelta(minutes=30))
    data = vehicle.to_dict()
    assert released and data["status"] == "returning"
    assert (data["origin_x"], data["origin_y"]) == (160.0, 150.0)
    assert (data["target_x"], data["target_y"]) == (gv.DEPOT_POSITION["x"], gv.DEPOT_POSITION["y"])
    pool.advance(T0 + timedelta(minutes=30 + back))
    assert vehicle.status == "available" and vehicle.to_dict()["target_x"] is None


def test_checkpoints_without_trip_fields_still_restore():
    vehicle = gv.GroundVehicle.__new__(gv.GroundVehicle)
    vehicle.__dict__.update({"id": "GV-FUE-001", "vehicle_type": "fuel_truck", "status": "available",
                             "current_gate": None, "position_x": 500.0, "position_y": 300.0,
                             "dispatched_at": None, "arrives_at": None, "task_name": None, "flight_id": None})
    data = vehicle.to_dict()
    assert data["origin_x"] is None and data["target_y"] is None


def test_trip_fields_survive_checkpoint_round_trip():
    from _common.checkpoint import SnapshotCodec

    class State:
        vehicle_pool = None

    codec = SnapshotCodec((gv.GroundVehicle, gv.GroundVehiclePool), ("vehicle_pool",))
    state = State()
    state.vehicle_pool = _pool()
    state.vehicle_pool.request_vehicle("fueling", "A01", "f1", T0)
    restored = State()
    codec.restore(restored, codec.dump(state))
    moving = [v for v in restored.vehicle_pool.vehicles.values() if v.status == "dispatched"]
    assert len(moving) == 1
    assert moving[0].to_dict()["target_x"] == 160.0
    assert moving[0].to_dict()["dispatched_at"] == T0.isoformat()


def test_flight_list_exposes_the_fsm_taxi_durations():
    spatial = import_service_module("flight", "services.spatial")
    runways = {"09L": {"threshold_x": 100.0, "threshold_y": 800.0}}
    gates = {"A01": {"position_x": 160.0, "position_y": 150.0}}
    initial, total = spatial.taxi_time_from_positions(runways["09L"], gates["A01"])
    assert spatial.taxi_durations("09L", "A01", runways, gates) == {
        "taxi_initial_minutes": round(initial, 3), "taxi_total_minutes": round(total, 3)}
    assert spatial.taxi_durations(None, None, runways, gates) == {
        "taxi_initial_minutes": 2.0, "taxi_total_minutes": 8.0}
