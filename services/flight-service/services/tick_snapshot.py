"""Versioned JSON checkpoint for flight tick-owned simulation state.

Only a fixed list of local types is accepted. No pickle, dynamic imports, or
executable values are read from storage. Configuration and external inputs
(weather, holds, incidents) are refreshed separately rather than rolled back
by restoring an older simulation checkpoint.
"""

from _common.checkpoint import SnapshotCodec

from services.runway_queue import RunwayQueue, RunwayQueueItem
from services.ground_vehicles import GroundVehicle, GroundVehiclePool
from services.turnaround_plan import TurnaroundPlan, TurnaroundTask, TaskStatus

TYPES = {t.__name__: t for t in (
    RunwayQueue, RunwayQueueItem, GroundVehicle, GroundVehiclePool,
    TurnaroundPlan, TurnaroundTask, TaskStatus,
)}
FIELDS = (
    "held_flights", "runway_queue", "turnaround_plans", "vehicle_pool", "task_vehicles",
    "crew_delay_drawn", "ctot_assigned", "equipment_failure_drawn", "diversion_drawn",
    "holding_minutes", "fuel_warned", "fuel_panpan", "current_mode", "last_mode",
    "last_sync_sim_time", "last_tick_sim_time", "vehicles_initialized",
    "weather_affected_runways", "weather_updated_at",
)


_codec = SnapshotCodec(tuple(TYPES.values()), FIELDS)
dump = _codec.dump
fields = FIELDS
publish_fields = ("incident_affected_gates", "incident_affected_runways")


def restore(state, document: str) -> None:
    updated_at = state.weather_updated_at
    affected = set(state.weather_affected_runways)
    capacity = {k: getattr(state.runway_queue, k) for k in (
        "_arrival_rate", "_departure_rate", "_weather_category", "_ils_required",
    )}
    _codec.restore(state, document)
    # Preserve a newer input received after the previous committed tick. A
    # fresh process has no such input and must retain checkpointed capacity.
    if updated_at is not None and (
        state.last_tick_sim_time is None or updated_at >= state.last_tick_sim_time
    ):
        state.runway_queue.__dict__.update(capacity)
        state.weather_affected_runways = affected
        state.weather_updated_at = updated_at
