"""Kafka consumer for baggage-service.

Consumes: SimClockTick, FlightStatusChanged, FlightCancelled,
          IncidentCreated (system_failure), IncidentStatusChanged
On each tick: advances conveyor pipeline, inducts new bags, screens items.
"""

from _common.transaction_scope import current as current_tick, run_tick, bind_transaction
from _common.checkpoint import SnapshotCodec
from services.conveyor import TransitBag, ZoneState
from _common import kafka_runtime
import logging
import os
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from _common.idempotency import IdempotencyTracker
from _common.consumer_health import ConsumerHealthTracker
from _common import outbox

from confluent_kafka import Consumer

from db.neo4j import (
    get_dropped_off_baggage_for_departures,
    get_driver,
    write_baggage_statuses_tx,
    next_outbox_revision_tx,
    begin_tick_tx,
    flag_baggage_tx,
    set_loaded_on_timestamps_tx,
    get_baggage_counts_by_status,
    get_baggage_in_pipeline,
    get_active_system_failures,
    redirect_baggage_to_flight_tx,
    get_baggage_by_id,
)
from kafka.producer import (
    emit_conveyor_delay,
    emit_bulk_state_snapshot,
    build_status_changed_fact,
    build_flagged_fact,
    set_bulk_mode,
    is_bulk_mode,
)
from services.conveyor import (
    ConveyorSystem,
    BagInZone,
)
from services.screening import screen_item
from services.offload import offload_flight_baggage
from metrics import (
    baggage_in_system as m_in_system,
    baggage_flagged_active as m_flagged,
    conveyor_zone_utilisation_pct as m_zone_util,
    conveyor_zone_status as m_zone_status,
    conveyor_segment_load as m_segment_load,
    conveyor_transit_queue as m_transit_queue,
    conveyor_delay_total as m_conveyor_delay,
    baggage_transitions_total as m_transitions,
    dangerous_goods_detected_total as m_dg_detected,
    screening_false_positives_total as m_false_pos,
    envelope_invalid_total as m_envelope_invalid,
    baggage_commands_total as m_commands,
)
from application.commands import parse_command, RedirectBaggage

logger = logging.getLogger(__name__)


def _track_transition(from_status: str, to_status: str) -> None:
    """Immediately update transition counter at mutation site."""
    m_transitions.labels(from_status=from_status, to_status=to_status).inc()


# ── Class-based state holder ────────────────────────────────


class BaggageConsumerState:
    """Holds all mutable runtime state for the baggage consumer."""

    MAX_PROCESSED = 20000

    def __init__(self) -> None:
        self.tick_counter = 0
        self.sim_time: datetime | None = None
        self.last_tick_sim_time: datetime | None = None
        self.conveyor = ConveyorSystem()
        self._idempotency = IdempotencyTracker(max_size=20_000)
        self.inducted_bag_ids: set[str] = set()
        self.active_failures: dict[str, str] = {}
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None
        # Speed mode tracking (REALTIME / FAST / BULK)
        self.current_mode: str = "REALTIME"
        self.last_mode: str = "REALTIME"
        self.last_sync_sim_time: datetime | None = None

    def check_idempotency(self, event_id: str) -> bool:
        return self._idempotency.is_duplicate(event_id)

    async def rebuild_from_neo4j(self) -> None:
        """Rebuild in-memory state from Neo4j on startup (catch-up)."""
        from db.neo4j import get_driver
        from _common.transaction_scope import restore_owner_checkpoint
        restored = await restore_owner_checkpoint("BaggageOutboxSeq", self, _TICK_CODEC, get_driver)
        self.active_failures = await get_active_system_failures()
        if restored:
            await _prepare_tick(self)
            return
        bags = await get_baggage_in_pipeline()
        self.conveyor = ConveyorSystem()
        self.inducted_bag_ids.clear()
        self.active_failures = await get_active_system_failures()
        for location in self.active_failures.values():
            for zone_id in FAILURE_IMPACT.get(location, []):
                self.conveyor.set_zone_status(zone_id, "offline")
        inducted = 0
        for bag in bags:
            tag = bag["id"]
            status = bag.get("status", "dropped_off")
            if status in ("inducted", "screening", "sorting", "arrived"):
                zone_id = bag.get("current_zone")
                if zone_id:
                    zone = self.conveyor.get_zone(zone_id)
                    if zone:
                        terminal = str(bag.get("terminal_id") or "T-A")[-1]
                        if terminal not in {"A", "B", "C"}:
                            terminal = "A"
                        gate_terminal = str(bag.get("gate_id") or terminal)[0]
                        zone.queue.append(BagInZone(
                            baggage_id=tag,
                            tag=bag.get("tag") or "",
                            flight_id=bag.get("flight_id", ""),
                            is_dg=bool(bag.get("is_dg")),
                            dg_class=bag.get("dg_class"),
                            passenger_id=bag.get("passenger_id"),
                            terminal=terminal,
                            gate_terminal=gate_terminal if gate_terminal in {"A", "B", "C"} else terminal,
                            entered_at=bag.get("last_scan_at") or "",
                        ))
                self.inducted_bag_ids.add(tag)
                inducted += 1
        logger.info("Rebuilt conveyor state from Neo4j: %d bags in pipeline, %d inducted total",
                     inducted, len(self.inducted_bag_ids))


# Module-level singleton
_state = BaggageConsumerState()
_consumer: Consumer | None = None
_consumer_running = False
_consumer_health = ConsumerHealthTracker()

# System failure impact mapping (constant, from SKILL.md)
FAILURE_IMPACT: dict[str, list[str]] = {
    "conveyor-sorting": ["sorting-matrix"],
    "conveyor-induction-A": ["induction-A"],
    "conveyor-induction-B": ["induction-B"],
    "conveyor-induction-C": ["induction-C"],
    "power-A": ["induction-A", "screening-unit-1", "screening-unit-2"],
    "power-B": ["induction-B", "screening-unit-3", "screening-unit-4"],
    "power-C": ["induction-C", "screening-unit-5", "screening-unit-6"],
    "screening-unit-1": ["screening-unit-1"],
    "screening-unit-2": ["screening-unit-2"],
    "screening-unit-3": ["screening-unit-3"],
    "screening-unit-4": ["screening-unit-4"],
    "screening-unit-5": ["screening-unit-5"],
    "screening-unit-6": ["screening-unit-6"],
}


def set_ws_broadcast(fn):
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.sim_time


def get_conveyor() -> ConveyorSystem:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.conveyor


def is_consumer_running() -> bool:
    return _consumer_running


def get_consumer_health() -> dict:
    """Return consumer health metrics for /health endpoint."""
    return _consumer_health.status()


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "bag-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
    })


def _bootstrap_clock(envelope: dict) -> None:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    if _state.sim_time is not None:
        return
    validated = _validate_envelope(envelope)
    if validated is not None and validated[0] == "SimClockTick":
        _state.sim_time = validated[1]


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    global _consumer, _consumer_running

    _consumer = _make_consumer()
    _consumer.subscribe(["sim.clock", "flights.events", "incidents.events", "baggage.commands"])
    _consumer_running = True

    logger.info(
        "Kafka consumer started (topics: sim.clock, flights.events, incidents.events, baggage.commands)"
    )

    try:
        await kafka_runtime.run_consumer_loop(
            _consumer, _dispatch, lambda: _consumer_running, _consumer_health,
            batch_size=5000, timeout=0.1, manual_commit=True,
            bootstrap_tick=_bootstrap_clock,
            commands_ready=lambda: _state.sim_time is not None,
        )
    finally:
        _consumer_running = False
        logger.info("Kafka consumer stopped")


def _validate_envelope(envelope: dict) -> tuple[str, datetime, dict] | None:
    """Validate Kafka envelope structure. Returns (event_type, sim_time, payload) or None."""
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str):
        m_envelope_invalid.labels(reason="missing_event_type").inc()
        logger.warning("Invalid envelope: missing/non-string event_type")
        return None

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        m_envelope_invalid.labels(reason="missing_sim_time").inc()
        logger.warning("Invalid envelope: missing sim_time for %s", event_type)
        return None
    try:
        sim_time = datetime.fromisoformat(str(sim_time_str)).replace(tzinfo=None)
    except (ValueError, TypeError):
        m_envelope_invalid.labels(reason="unparseable_sim_time").inc()
        logger.warning("Invalid envelope: unparseable sim_time '%s'", sim_time_str)
        return None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        m_envelope_invalid.labels(reason="missing_payload").inc()
        logger.warning("Invalid envelope: missing/non-dict payload for %s", event_type)
        return None

    return event_type, sim_time, payload


async def _dispatch(envelope: dict) -> None:
    """Route events to handlers based on event_type.

    Command envelopes (keyed on ``command_type``, from ``baggage.commands``)
    are imperatives, not facts — they take a separate path.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    # Commands are keyed on command_type (no event_type / sim_time).
    if envelope.get("command_type") is not None:
        await _handle_command(envelope)
        return

    validated = _validate_envelope(envelope)
    if validated is None:
        return
    event_type, sim_time, payload = validated

    # Idempotency check (skip for clock ticks — they're always unique)
    event_id = envelope.get("event_id", "")
    if event_type != "SimClockTick":
        if event_id and event_id in _state._idempotency:
            return

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case "FlightStatusChanged":
            await _on_flight_status_changed(payload, sim_time, event_id)
        case "FlightCancelled":
            await _on_flight_cancelled(payload, sim_time)
        case "IncidentCreated":
            await _on_incident_created(payload, sim_time)
        case "IncidentStatusChanged":
            await _on_incident_status_changed(payload, sim_time)
        case _:
            pass

    _state.check_idempotency(envelope.get("event_id", ""))





async def _handle_command(envelope: dict) -> None:
    """The mutation and every receipt delivery use the durable outbox."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    command_id = envelope.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise ValueError("command_id is required")
    if _state.sim_time is None:
        raise RuntimeError("Simulation clock not available")
    await _execute_command(envelope)


async def _stage_receipt(tx, receipt, sim_time, revision):
    document = kafka_runtime.build_envelope(receipt[0], sim_time, receipt[1], "baggage-service")
    await outbox.stage_outbox(tx, "BaggageOutbox", [
        {"id": document["event_id"], "document": document},
    ], revision)


def _command_receipt(command_id, command_type, reason) -> tuple[str, dict]:
    """Durable owner outcome; redelivery stages this same outcome without mutation."""
    return (
        "CommandRejected" if reason else "CommandExecuted",
        {"command_id": command_id, "command_type": command_type, "reason": reason},
    )


async def _commit_receipt_only(command_id: str, receipt: tuple[str, dict]) -> None:
    """Persist a rejection receipt atomically (no domain mutation, no fact)."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from _common.command_store import load_receipt_in_tx, save_receipt_in_tx

    async def apply(tx) -> None:
        revision = await next_outbox_revision_tx(tx)
        existing = await load_receipt_in_tx(tx, command_id)
        if existing is None:
            await save_receipt_in_tx(tx, command_id, receipt)
        await _stage_receipt(tx, existing or receipt, _state.sim_time, revision)

    async with get_driver().session() as session:
        await session.execute_write(apply)


async def _execute_command(envelope: dict) -> str | None:
    """Execute a ``baggage.commands`` command atomically (G1-b).

    Parses/validates, then — for ``RedirectBaggage`` — re-assigns the LOADED_ON
    relationship, stages the ``BaggageStatusChanged`` fact and writes the command
    receipt in ONE transaction. The conveyor eviction (rebuildable cache) and
    receipt fact in ONE transaction. Metrics/cache eviction follow commit.
    Returns the rejection reason, or ``None`` on success.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from _common.command_store import load_receipt_in_tx, save_receipt_in_tx

    command_type = envelope.get("command_type")
    command_id = envelope.get("command_id")
    cmd, error = parse_command(command_type, envelope.get("payload"))
    if error is not None:
        await _commit_receipt_only(command_id, _command_receipt(command_id, command_type, error))
        m_commands.labels(command_type=str(command_type), outcome="rejected").inc()
        logger.warning("Rejected command %s: %s", command_type, error)
        return error

    # handle() guarantees sim_time is not None before calling execute.
    sim_time = _state.sim_time

    assert isinstance(cmd, RedirectBaggage)
    outcome: dict = {"reason": None, "result": None}

    async def apply(tx) -> None:
        revision = await next_outbox_revision_tx(tx)
        existing = await load_receipt_in_tx(tx, command_id)
        if existing is not None:
            # Durable redelivery raced past handle()'s load — re-emit, don't re-mutate.
            outcome["reason"] = existing[1].get("reason")
            outcome["result"] = "seen"
            await _stage_receipt(tx, existing, sim_time, revision)
            return
        with bind_transaction(tx):
            bag = await get_baggage_by_id(cmd.bag_id)
        if bag is None:
            reason = "Baggage not found"
            receipt = _command_receipt(command_id, command_type, reason)
            await save_receipt_in_tx(tx, command_id, receipt)
            await _stage_receipt(tx, receipt, sim_time, revision)
            outcome.update(reason=reason, result="rejected")
            return
        prev_status = bag.get("status", "unknown")
        passenger_id = (bag.get("passenger") or {}).get("id")
        tag = bag.get("tag", "")
        outcome["previous_status"] = prev_status
        ok = await redirect_baggage_to_flight_tx(
            tx, cmd.bag_id, cmd.target_flight_id, sim_time
        )
        if not ok:
            reason = "Target flight not found"
            await save_receipt_in_tx(
                tx, command_id, _command_receipt(command_id, command_type, reason)
            )
            outcome["reason"] = reason
            outcome["result"] = "rejected"
            await _stage_receipt(tx, _command_receipt(command_id, command_type, reason), sim_time, revision)
            return
        facts = [
            _status_changed_fact(
                event_id=command_id,
                baggage_id=cmd.bag_id,
                tag=tag,
                previous_status=prev_status,
                new_status="redirected",
                scan_zone="redirected",
                sim_time=sim_time,
                passenger_id=passenger_id,
                flight_id=cmd.target_flight_id,
            )
        ]
        document = kafka_runtime.build_envelope("CommandExecuted", sim_time,
            _command_receipt(command_id, command_type, None)[1], "baggage-service")
        facts.append({"id": document["event_id"], "document": document})
        await outbox.stage_outbox(tx, "BaggageOutbox", facts, revision)
        await save_receipt_in_tx(
            tx, command_id, _command_receipt(command_id, command_type, None)
        )
        outcome["result"] = "executed"

    async with get_driver().session() as session:
        await session.execute_write(apply)

    if outcome["result"] == "rejected":
        m_commands.labels(command_type=command_type, outcome="rejected").inc()
        logger.warning(
            "Rejected RedirectBaggage: target flight %s not found", cmd.target_flight_id
        )
    elif outcome["result"] == "executed":
        # Post-commit only: evict from the rebuildable conveyor cache + metric.
        _state.conveyor.remove_bag_from_all_zones(cmd.bag_id)
        _track_transition(outcome["previous_status"], "redirected")
        m_commands.labels(command_type=command_type, outcome="accepted").inc()
        logger.info(
            "Executed RedirectBaggage: bag %s → flight %s",
            cmd.bag_id, cmd.target_flight_id,
        )
    return outcome["reason"]


BULK_SNAPSHOT_INTERVAL_SIM_MIN = int(os.getenv("BULK_SNAPSHOT_INTERVAL_MIN", "60"))


class _TickPlan:
    """Everything one tick intends to do — computed first, applied in one tx.

    ``status_changes`` (batched BaggageStatusChanged transitions), ``flags``
    (screening DG flags), ``loaded_rows`` (LOADED_ON timestamps) are the durable
    writes; ``facts`` is the ordered outbox payload; ``inducted_ids`` / ``ws`` /
    ``metrics`` are post-commit cache + fan-out + counter effects.
    """

    def __init__(self) -> None:
        self.status_changes: list[dict] = []
        self.flags: list[dict] = []
        self.loaded_rows: list[dict] = []
        self.facts: list[dict] = []
        self.inducted_ids: list[str] = []
        self.ws: list[tuple[str, dict]] = []
        self.metrics: list[tuple] = []


def _plan_status_change(
    plan: _TickPlan,
    bag: BagInZone,
    previous_status: str,
    new_status: str,
    zone: str,
    sim_time: datetime,
    *,
    suppress: bool,
    loaded_flight_id: str | None = None,
) -> None:
    """Append one BaggageStatusChanged transition to the tick plan."""
    plan.status_changes.append({"id": bag.baggage_id, "status": new_status, "zone": zone})
    plan.metrics.append(("transition", previous_status, new_status))
    if loaded_flight_id:
        plan.loaded_rows.append({"baggage_id": bag.baggage_id, "flight_id": loaded_flight_id})
    if not suppress:
        fact = build_status_changed_fact(
            id_base=sim_time.isoformat(),
            baggage_id=bag.baggage_id,
            tag=bag.tag,
            previous_status=previous_status,
            new_status=new_status,
            scan_zone=zone,
            sim_time=sim_time,
            passenger_id=bag.passenger_id,
            flight_id=bag.flight_id,
        )
        plan.facts.append(fact)
        plan.ws.append(("BaggageStatusChanged", fact["document"]["payload"]))


async def _apply_tick(plan: _TickPlan, sim_time: datetime) -> bool:
    """Commit the whole tick in ONE transaction (A41 per-tick atomicity).

    Locks the ``BaggageOutboxSeq`` runtime, early-returns on replay/crash-resume
    (``sim_time <= last_tick``), then bulk-writes every transition (+ScanEvents,
    +flags, +LOADED_ON timestamps), stages all facts at the runtime revision, and
    advances ``last_tick_sim_time`` — all or nothing. Returns True if applied,
    False if skipped as a replay.
    """
    async def apply(tx) -> bool:
        proceed, revision = await begin_tick_tx(tx, sim_time.isoformat())
        if not proceed:
            return False
        await write_baggage_statuses_tx(tx, plan.status_changes, sim_time)
        for flag in plan.flags:
            await flag_baggage_tx(
                tx, flag["baggage_id"], flag["flag_reason"], flag["scan_zone"], sim_time
            )
        await set_loaded_on_timestamps_tx(tx, plan.loaded_rows, sim_time)
        facts = list(plan.facts)
        facts.extend(outbox.transition_batch_facts(
            "BaggageStatusBatchChanged", sim_time, "baggage-service", {
                "status_changes": plan.status_changes, "flags": plan.flags,
                "loaded_rows": plan.loaded_rows,
            },
        ))
        await outbox.stage_outbox(tx, "BaggageOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


def _apply_tick_metrics(plan: _TickPlan) -> None:
    """Apply counter effects post-commit (mutation-site timing preserved)."""
    for op in plan.metrics:
        if op[0] == "transition":
            m_transitions.labels(from_status=op[1], to_status=op[2]).inc()
        elif op[0] == "flag_dg":
            m_dg_detected.labels(dg_class=op[1]).inc()
            m_flagged.inc(1)
        elif op[0] == "flag_fp":
            m_false_pos.inc()



_TICK_CODEC = SnapshotCodec(
    [ConveyorSystem, BagInZone, TransitBag, ZoneState],
    (
        "last_tick_sim_time", "conveyor", "inducted_bag_ids", "current_mode",
        "last_mode", "last_sync_sim_time", "tick_counter",
    ),
)


async def _prepare_tick(candidate: BaggageConsumerState) -> None:
    # External redirects/offloads may have removed a checkpointed queued bag.
    pipeline = await get_baggage_in_pipeline()
    bags = {bag["id"] for bag in pipeline}
    present = set()
    for zone in candidate.conveyor.get_all_zones().values():
        zone.queue = type(zone.queue)(b for b in zone.queue if b.baggage_id in bags)
        present.update(b.baggage_id for b in zone.queue)
        zone.status = "normal"
    candidate.conveyor._transit_queue = [
        b for b in candidate.conveyor._transit_queue if b.bag.baggage_id in bags
    ]
    present.update(b.bag.baggage_id for b in candidate.conveyor._transit_queue)
    for bag in pipeline:
        candidate.inducted_bag_ids.add(bag["id"])
        if bag["id"] in present or bag.get("status") not in {
            "inducted", "screening", "sorting", "arrived", "offloaded",
        }:
            continue
        zone = candidate.conveyor.get_zone(bag.get("current_zone"))
        if zone is None:
            continue
        terminal = str(bag.get("terminal_id") or "T-A")[-1]
        terminal = terminal if terminal in "ABC" else "A"
        destination = str(bag.get("gate_id") or terminal)[0]
        zone.queue.append(BagInZone(
            baggage_id=bag["id"], tag=bag.get("tag") or "",
            flight_id=bag.get("flight_id") or "", is_dg=bool(bag.get("is_dg")),
            dg_class=bag.get("dg_class"), passenger_id=bag.get("passenger_id"),
            terminal=terminal, gate_terminal=destination if destination in "ABC" else terminal,
            entered_at=bag.get("last_scan_at") or "",
        ))
    for location in candidate.active_failures.values():
        for zone_id in FAILURE_IMPACT.get(location, []):
            candidate.conveyor.set_zone_status(zone_id, "offline")


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    from db.neo4j import get_driver
    await run_tick("BaggageOutboxSeq", "BaggageOutbox", _state,
                   _TICK_CODEC, get_driver, _advance_tick, payload, sim_time, _prepare_tick)


async def _advance_tick(payload: dict, sim_time: datetime) -> None:
    """Process SimClockTick — induct new bags and advance conveyor pipeline.

    G1-a: the whole tick's domain writes + facts + checkpoint commit in one
    transaction (``_apply_tick``). The in-memory conveyor (a rebuildable cache)
    is advanced during the compute phase under a snapshot; on a failed or
    replayed tick it is rolled back to that snapshot so the cache never drifts
    ahead of the committed graph.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    _state.tick_counter += 1
    _baggage_tick_n = _state.tick_counter
    _state.sim_time = sim_time

    # In-memory replay guard; the durable backstop is begin_tick_tx in the tx.
    if _state.last_tick_sim_time is not None and sim_time <= _state.last_tick_sim_time:
        return

    # Compute delta for multi-minute ticks / tick skipping
    if _state.last_tick_sim_time is not None:
        delta_minutes = max(1, round((sim_time - _state.last_tick_sim_time).total_seconds() / 60))
    else:
        delta_minutes = payload.get("step_minutes", 1)

    # Track simulation mode (REALTIME / FAST / BULK)
    _state.last_mode = _state.current_mode
    _state.current_mode = payload.get("mode", "REALTIME")
    is_bulk = _state.current_mode == "BULK"
    set_bulk_mode(is_bulk)

    sim_time_str = sim_time.isoformat()

    # ── compute phase: mutate the in-memory conveyor under a rollback snapshot ──
    conveyor_snapshot = deepcopy(_state.conveyor)
    plan = _TickPlan()
    # 1. Induct new bags (dropped_off → inducted / fast-tracked in_hold)
    await _plan_induction(plan, sim_time, delta_minutes)
    # 2. Advance conveyor pipeline
    outputs = _state.conveyor.advance_tick(sim_time_str, delta_minutes)
    # 3. Plan zone-exit transitions (each bag leaves at most one zone per tick)
    exits = [(zone_id, bag) for zone_id, bags in outputs.items() for bag in bags]
    for zone_id, bag in exits:
        _plan_bag_exit(plan, zone_id, bag, sim_time)

    # ── atomic apply: all transitions + facts + checkpoint in one tx ──
    try:
        committed = await _apply_tick(plan, sim_time)
    except Exception:
        _state.conveyor = conveyor_snapshot  # roll back the in-memory advance
        raise
    if not committed:
        # Durable replay/crash-resume: this tick was already applied; discard the
        # recomputed advance and realign the in-memory checkpoint.
        _state.conveyor = conveyor_snapshot
        _state.last_tick_sim_time = sim_time
        return

    # ── post-commit only: caches, metrics, WS fan-out ──
    _state.last_tick_sim_time = sim_time
    _state.inducted_bag_ids.update(plan.inducted_ids)
    _apply_tick_metrics(plan)
    if _state.ws_broadcast:
        for event_type, ws_payload in plan.ws:
            await _state.ws_broadcast({"event_type": event_type, "payload": ws_payload})

    # 4. Update Prometheus gauges (reduced frequency in BULK mode)
    gauge_interval = 20 if is_bulk else 1
    if _baggage_tick_n % gauge_interval == 0:
        try:
            counts = await get_baggage_counts_by_status()
            for status, count in counts.items():
                m_in_system.labels(status=status).set(count)
        except Exception:
            pass
    for z in _state.conveyor.get_zone_summary():
        m_zone_util.labels(zone_id=z["zone_id"]).set(z["utilisation_pct"])
        status_val = {"normal": 0, "degraded": 1, "offline": 2}.get(z["status"], 0)
        m_zone_status.labels(zone_id=z["zone_id"]).set(status_val)
        # GAP-4-8: per-segment load metric
        m_segment_load.labels(zone_id=z["zone_id"]).set(z["items"])
    m_transit_queue.set(_state.conveyor.transit_queue_depth)

    if _baggage_tick_n % gauge_interval == 0:
        from db.neo4j import save_zone_projection
        from kafka.producer import emit_zone_snapshot
        snapshot = {"zones": _state.conveyor.get_zone_summary(), "at": sim_time.isoformat()}
        await save_zone_projection(snapshot)
        emit_zone_snapshot(snapshot, sim_time)

    # 5. GAP-4-5/4-6: Check make-up carousel capacity overflow
    if _baggage_tick_n % 5 == 0:  # check every 5 ticks to avoid spam
        overloaded = _state.conveyor.get_overloaded_makeup_zones()
        for info in overloaded:
            m_conveyor_delay.labels(terminal=info["terminal"]).inc()
            await emit_conveyor_delay(
                zone_id=info["zone_id"],
                terminal=info["terminal"],
                items=info["items"],
                capacity=info["capacity"],
                overflow=info["overflow"],
                estimated_delay_min=info["estimated_delay_min"],
                sim_time=sim_time,
            )

    # 6. BULK mode: emit periodic BulkStateSnapshot
    #    Also emit on BULK→non-BULK transition (forced flush)
    leaving_bulk = _state.last_mode == "BULK" and _state.current_mode != "BULK"
    if is_bulk or leaving_bulk:
        await _maybe_emit_baggage_bulk_snapshot(sim_time)


async def _maybe_emit_baggage_bulk_snapshot(sim_time: datetime) -> None:
    """Emit a BulkStateSnapshot summarising baggage state (BULK mode only)."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    force = _state.last_mode == "BULK" and _state.current_mode != "BULK"

    if not force and _state.last_sync_sim_time is not None:
        elapsed = (sim_time - _state.last_sync_sim_time).total_seconds() / 60
        if elapsed < BULK_SNAPSHOT_INTERVAL_SIM_MIN:
            return

    _state.last_sync_sim_time = sim_time

    try:
        counts = await get_baggage_counts_by_status()
    except Exception:
        counts = {}

    zone_summary = _state.conveyor.get_zone_summary()
    summary = {
        "by_status": counts,
        "zones": {z["zone_id"]: z["utilisation_pct"] for z in zone_summary},
    }

    emit_bulk_state_snapshot(sim_time, summary)
    logger.info("BulkStateSnapshot emitted (baggage): %s", counts)


async def _plan_induction(plan: _TickPlan, sim_time: datetime, delta_minutes: int = 1) -> None:
    """Plan induction of dropped_off bags (no DB write — folded into the tick tx).

    For flights already departed/airborne, fast-track to 'in_hold'. For flights
    still at the airport within the 90-min window, induct onto the belt. The
    in-memory conveyor (rebuildable cache) is populated here in the compute phase
    under ``_on_clock_tick``'s snapshot; the ``inducted_ids`` are added to the
    cache only after the tick commits.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    try:
        bags = await get_dropped_off_baggage_for_departures(sim_time)
    except Exception as e:
        logger.error("Failed to query dropped_off bags: %s", e)
        raise

    sim_time_str = sim_time.isoformat()
    suppress = is_bulk_mode()
    batch_count = 0
    MAX_BATCH_PER_TICK = 500 * delta_minutes

    for bag in bags:
        if batch_count >= MAX_BATCH_PER_TICK:
            break

        bag_id = bag["id"]
        # Skip if already inducted (durable cache or already planned this tick)
        if bag_id in _state.inducted_bag_ids or bag_id in plan.inducted_ids:
            continue

        flight_status = bag.get("flight_status", "scheduled")

        # For flights already departed/airborne — fast-track to in_hold
        if flight_status in ("departed", "airborne"):
            batch_count += 1
            bag_in_zone = None
            status, zone = "in_hold", "aircraft-hold"
        else:
            # For flights still at the airport: check 90-min window
            est_time_str = bag.get("estimated_time")
            if est_time_str:
                try:
                    est_time = datetime.fromisoformat(str(est_time_str)).replace(tzinfo=None)
                    if est_time - sim_time > timedelta(minutes=90):
                        continue
                except (ValueError, TypeError):
                    pass

            batch_count += 1

            # Determine terminal from gate assignment (fallback to round-robin)
            terminal = "A"
            terminal_id = bag.get("terminal_id")
            if terminal_id and len(str(terminal_id)) >= 3:
                terminal = str(terminal_id)[-1]
            if terminal not in "ABC":
                terminal = "A"

            # Determine gate's terminal for cross-terminal transit time
            gate_terminal = terminal
            gate_id = bag.get("gate_id")
            if gate_id and len(str(gate_id)) >= 1:
                gt = str(gate_id)[0].upper()
                if gt in "ABC":
                    gate_terminal = gt

            bag_in_zone = BagInZone(
                baggage_id=bag_id,
                tag=bag["tag"],
                flight_id=bag.get("flight_id", ""),
                is_dg=bool(bag.get("is_dg")),
                dg_class=bag.get("dg_class"),
                passenger_id=bag.get("passenger_id"),
                terminal=terminal,
                entered_at=sim_time_str,
                gate_terminal=gate_terminal,
            )
            status, zone = "inducted", f"induction-{terminal}"

        plan.status_changes.append({"id": bag_id, "status": status, "zone": zone})
        plan.inducted_ids.append(bag_id)
        plan.metrics.append(("transition", "dropped_off", status))
        if bag_in_zone is not None:
            _state.conveyor.induct_bag(bag_in_zone, sim_time_str)
        if not suppress:
            fact = build_status_changed_fact(
                id_base=sim_time_str,
                baggage_id=bag_id,
                tag=bag["tag"],
                previous_status="dropped_off",
                new_status=status,
                scan_zone=zone,
                sim_time=sim_time,
                passenger_id=bag.get("passenger_id"),
                flight_id=bag.get("flight_id"),
            )
            plan.facts.append(fact)
            plan.ws.append(("BaggageStatusChanged", fact["document"]["payload"]))


def _plan_bag_exit(
    plan: _TickPlan, from_zone: str, bag: BagInZone, sim_time: datetime
) -> None:
    """Plan a bag's zone-exit transition(s) — screen, flag, or advance status.

    No DB write and no fact emission happen here; everything is appended to
    ``plan`` and applied atomically by ``_apply_tick``. The only in-memory
    mutation is the flag eviction from the conveyor (compute-phase, covered by
    ``_on_clock_tick``'s rollback snapshot).
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    suppress = is_bulk_mode()

    if from_zone.startswith("induction"):
        # advance_tick already placed the bag in a screening zone
        screening_zone = _find_bag_current_zone(bag.baggage_id)
        if screening_zone:
            _plan_status_change(
                plan, bag, "inducted", "screening", screening_zone, sim_time,
                suppress=suppress,
            )

    elif from_zone.startswith("screening"):
        result = screen_item(bag.baggage_id, bag.is_dg, bag.dg_class)
        if result in ("flagged", "false_positive"):
            flag_reason = (
                "dangerous_goods_detected" if result == "flagged" else "false_positive"
            )
            plan.flags.append({
                "baggage_id": bag.baggage_id,
                "flag_reason": flag_reason,
                "scan_zone": from_zone,
            })
            plan.metrics.append(
                ("flag_dg", str(bag.dg_class or "unknown")) if result == "flagged"
                else ("flag_fp",)
            )
            # Remove from sorting queue (advance_tick already placed it there).
            _state.conveyor.remove_bag_from_all_zones(bag.baggage_id)
            # BaggageFlagged facts are never suppressed in BULK mode (safety fact).
            fact = build_flagged_fact(
                id_base=sim_time.isoformat(),
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                flag_reason=flag_reason,
                scan_zone=from_zone,
                sim_time=sim_time,
                dg_class=bag.dg_class,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            plan.facts.append(fact)
            plan.ws.append(("BaggageFlagged", fact["document"]["payload"]))
        else:
            _plan_status_change(
                plan, bag, "screening", "sorting", "sorting-matrix", sim_time,
                suppress=suppress,
            )

    elif from_zone == "sorting-matrix":
        makeup_zone = _find_bag_current_zone(bag.baggage_id)
        if makeup_zone:
            _plan_status_change(
                plan, bag, "sorting", "loaded", makeup_zone, sim_time,
                suppress=suppress, loaded_flight_id=bag.flight_id or None,
            )

    elif from_zone.startswith("make-up"):
        _plan_status_change(
            plan, bag, "sorting", "loaded", from_zone, sim_time,
            suppress=suppress, loaded_flight_id=bag.flight_id or None,
        )

    elif from_zone.startswith("arrival-belt"):
        # arrived → on_carousel (visible) → collected (picked up), same tick
        _plan_status_change(
            plan, bag, "arrived", "on_carousel", from_zone, sim_time, suppress=suppress,
        )
        _plan_status_change(
            plan, bag, "on_carousel", "collected", from_zone, sim_time, suppress=suppress,
        )


def _find_bag_current_zone(baggage_id: str) -> str | None:
    """Find which zone a bag is currently in (in-memory lookup)."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    for zone_id, zone in _state.conveyor.get_all_zones().items():
        for bag in zone.queue:
            if bag.baggage_id == baggage_id:
                return zone_id
    return None


async def _on_flight_status_changed(
    payload: dict, sim_time: datetime, event_id: str = ""
) -> None:
    """React to flight status changes — handle departures and arrivals."""
    new_status = payload.get("new_status")
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    if new_status == "departed":
        # Flight departed — all bags on this flight → 'in_hold' (canonical G1
        # atomic path: see _apply_departure_in_hold).
        await _apply_departure_in_hold(flight_id, sim_time, event_id)

    elif new_status == "at_gate" and payload.get("previous_status") in (
        "taxiing", "landed"
    ):
        # Arrival flight reached gate — bags 'in_hold' → 'arrived' (queued on belt).
        await _apply_arrival_at_gate(
            flight_id, payload.get("gate_id") or "", sim_time, event_id
        )

    elif new_status == "cancelled":
        # Flight cancelled — offload all baggage
        await _on_flight_cancelled(payload, sim_time)


def _status_changed_fact(
    *,
    event_id: str,
    baggage_id: str,
    tag: str,
    previous_status: str,
    new_status: str,
    scan_zone: str,
    sim_time: datetime,
    passenger_id: str | None,
    flight_id: str | None,
) -> dict:
    """Build one BaggageStatusChanged outbox fact: ``{"id", "document"}``.

    ``document`` is the full event envelope that ``publish_confirmed`` will
    produce verbatim. The envelope's ``event_id`` is a *stable*, deterministic id
    (derived from the input event) so a Kafka redelivery of the input re-stages
    the identical fact id — at-least-once with stable IDs, not exactly-once.

    Thin wrapper over :func:`kafka.producer.build_status_changed_fact` (shared
    with the offload / tick paths) preserving the historical ``id`` format.
    """
    return build_status_changed_fact(
        id_base=event_id,
        baggage_id=baggage_id,
        tag=tag,
        previous_status=previous_status,
        new_status=new_status,
        scan_zone=scan_zone,
        sim_time=sim_time,
        passenger_id=passenger_id,
        flight_id=flight_id,
    )


async def _apply_departure_in_hold(
    flight_id: str, sim_time: datetime, event_id: str
) -> None:
    """Flight departed → all its bags go to 'in_hold', atomically (gap G1).

    Bags still in the conveyor (inducted/screening/sorting) or not yet inducted
    (dropped_off) are fast-tracked: in reality they would have been processed
    before departure. Within ONE ``session.execute_write`` we (a) check the
    durable BaggageInbox and skip if this input was already applied, (b) write
    the bag status + ScanEvent trail, (c) mark the inbox, and (d) stage the
    BaggageStatusChanged facts in the outbox — so a crash can never leave the
    domain mutated without the facts staged, nor re-apply on redelivery. The
    in-memory conveyor (a Neo4j-derived, rebuildable cache per rule #3) and the
    WebSocket fan-out run only *after* the commit succeeds.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from db.neo4j import get_flight_baggage
    bags = await get_flight_baggage(
        flight_id,
        statuses=["loaded", "sorting", "screening", "inducted", "dropped_off"],
    )
    if not bags:
        return

    changes = [
        {"id": bag["id"], "status": "in_hold", "zone": "aircraft-hold"} for bag in bags
    ]
    # BULK speed mode suppresses per-bag facts (aggregated via BulkStateSnapshot),
    # matching emit_baggage_status_changed; the domain write + inbox stay atomic.
    suppress = is_bulk_mode()
    facts = [] if suppress else [
        _status_changed_fact(
            event_id=event_id,
            baggage_id=bag["id"],
            tag=bag["tag"],
            previous_status=bag.get("status", "loaded"),
            new_status="in_hold",
            scan_zone="aircraft-hold",
            sim_time=sim_time,
            passenger_id=bag.get("passenger_id"),
            flight_id=flight_id,
        )
        for bag in bags
    ]

    async def apply(tx) -> bool:
        if await outbox.inbox_seen(tx, "BaggageInbox", event_id):
            return False  # durable dedup: already applied — no re-write, no re-stage
        revision = await next_outbox_revision_tx(tx)
        await write_baggage_statuses_tx(tx, changes, sim_time)
        await outbox.mark_inbox(tx, "BaggageInbox", event_id, sim_time.isoformat())
        await outbox.stage_outbox(tx, "BaggageOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        applied = await session.execute_write(apply)

    if not applied:
        return

    # Post-commit only: derived cache + fan-out + metrics. Safe to re-run on a
    # redelivery whose commit ack was lost (the write above is idempotent).
    for bag in bags:
        _state.conveyor.remove_bag_from_all_zones(bag["id"])
        _track_transition(bag.get("status", "loaded"), "in_hold")
    if _state.ws_broadcast and not suppress:
        for fact in facts:
            await _state.ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": fact["document"]["payload"],
            })


async def _apply_arrival_at_gate(
    flight_id: str, gate_id: str, sim_time: datetime, event_id: str
) -> None:
    """Arrival reached gate → its 'in_hold' bags go to 'arrived', atomically (G1-c).

    Within ONE ``session.execute_write`` we (a) skip via the durable BaggageInbox
    if this input was already applied, (b) write the 'arrived' status + ScanEvent,
    (c) mark the inbox, and (d) stage the BaggageStatusChanged facts. The bags
    then stay 'arrived' until later ticks drain the belt (on_carousel → collected).
    Placing bags on the in-memory arrival belt (a rebuildable cache) + WS fan-out
    + metrics run only *after* the commit succeeds.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from db.neo4j import get_flight_baggage
    from services.spatial import arrival_carousel_for_terminal

    bags = await get_flight_baggage(flight_id, statuses=["in_hold"])
    if not bags:
        return

    # Determine terminal from gate_id (first char) per ROADMAP: A→1-2, B→3-4, C→5-6
    terminal = gate_id[0].upper() if gate_id else "A"
    terminal_carousels = arrival_carousel_for_terminal(terminal)
    carousel = terminal_carousels[hash(flight_id) % len(terminal_carousels)]
    zone = f"arrival-belt-{carousel}"

    changes = [
        {"id": bag["id"], "status": "arrived", "zone": zone, "carousel": carousel}
        for bag in bags
    ]
    suppress = is_bulk_mode()
    facts = [] if suppress else [
        _status_changed_fact(
            event_id=event_id,
            baggage_id=bag["id"],
            tag=bag["tag"],
            previous_status="in_hold",
            new_status="arrived",
            scan_zone=zone,
            sim_time=sim_time,
            passenger_id=bag.get("passenger_id"),
            flight_id=flight_id,
        )
        for bag in bags
    ]

    async def apply(tx) -> bool:
        if await outbox.inbox_seen(tx, "BaggageInbox", event_id):
            return False
        revision = await next_outbox_revision_tx(tx)
        await write_baggage_statuses_tx(tx, changes, sim_time)
        await outbox.mark_inbox(tx, "BaggageInbox", event_id, sim_time.isoformat())
        await outbox.stage_outbox(tx, "BaggageOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        applied = await session.execute_write(apply)

    if not applied:
        return

    # Post-commit only: derived arrival-belt cache + fan-out + metrics.
    for bag in bags:
        bag_in_zone = BagInZone(
            baggage_id=bag["id"],
            tag=bag["tag"],
            flight_id=flight_id,
            is_dg=False,
            dg_class=None,
            passenger_id=bag.get("passenger_id"),
            terminal=terminal,
            entered_at=sim_time.isoformat(),
        )
        arrival_zone = _state.conveyor.get_zone(zone)
        if arrival_zone:
            arrival_zone.queue.append(bag_in_zone)
        _track_transition("in_hold", "arrived")
    if _state.ws_broadcast and not suppress:
        for fact in facts:
            await _state.ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": fact["document"]["payload"],
            })


async def _on_flight_cancelled(payload: dict, sim_time: datetime) -> None:
    """Handle FlightCancelled — offload all loaded baggage (G1-c atomic path)."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    offloaded = await offload_flight_baggage(
        flight_id=flight_id,
        sim_time=sim_time,
        conveyor_system=_state.conveyor,
    )
    # Post-commit only: per-transition metrics for the committed offloads.
    for bag in offloaded:
        _track_transition(bag["previous_status"], "offloaded")


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — halt affected conveyor zones."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    incident_type = payload.get("type")
    if incident_type != "system_failure":
        return

    location = payload.get("location", "")
    incident_id = payload.get("incident_id")
    if not incident_id:
        return
    _state.active_failures[incident_id] = location
    affected_zones = FAILURE_IMPACT.get(location, [])
    for zone_id in affected_zones:
        _state.conveyor.set_zone_status(zone_id, "offline")
        m_zone_status.labels(zone_id=zone_id).set(2)  # offline
        logger.warning(
            "Zone %s set OFFLINE due to system_failure at %s",
            zone_id, location,
        )


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentStatusChanged — resume zones when incident resolved."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    new_status = payload.get("new_status") or payload.get("status")
    if new_status != "resolved":
        return

    incident_id = payload.get("incident_id")
    if not incident_id:
        return
    if payload.get("type") != "system_failure" and incident_id not in _state.active_failures:
        return
    location = _state.active_failures.pop(incident_id, payload.get("location", ""))
    affected_zones = FAILURE_IMPACT.get(location, [])
    for zone_id in affected_zones:
        if any(zone_id in FAILURE_IMPACT.get(other, []) for other in _state.active_failures.values()):
            continue
        _state.conveyor.set_zone_status(zone_id, "normal")
        m_zone_status.labels(zone_id=zone_id).set(0)  # normal
        logger.info(
            "Zone %s restored to NORMAL after incident resolved at %s",
            zone_id, location,
        )
