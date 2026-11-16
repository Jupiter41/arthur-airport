"""Owner tick transaction scope, explicitly shared by repositories and producer.

Nested repository sessions borrow the owning tick transaction; they cannot
commit it or open a second connection. ContextVars keep REST/outbox tasks out.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, Sequence
from datetime import datetime

class Checkpoint(Protocol):
    fields: Sequence[str]

    def dump(self, state: Any) -> str: ...

    def restore(self, state: Any, document: str) -> None: ...


@dataclass
class TickScope:
    tx: Any
    state: Any
    facts: list[dict] = field(default_factory=list)
    broadcasts: list[dict] = field(default_factory=list)
    flushing: bool = False
    effects: list[Callable[[], None]] = field(default_factory=list)


current: ContextVar[TickScope | None] = ContextVar("owner_tick", default=None)
borrowed: ContextVar[TickScope | None] = ContextVar("owner_command_tx", default=None)


@contextmanager
def bind_transaction(tx: Any):
    """Borrow a command transaction for repository reads, without capturing facts."""
    token = borrowed.set(TickScope(tx, None))
    try:
        yield
    finally:
        borrowed.reset(token)


class TransactionDriver:
    def __init__(self, scope: TickScope) -> None:
        self.scope = scope

    def session(self) -> "TransactionDriver":
        return self

    async def __aenter__(self) -> "TransactionDriver":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def run(self, query: str, **params: Any) -> Any:
        return await self.scope.tx.run(query, **params)

    async def execute_write(self, callback: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        return await callback(self.scope.tx, *args, **kwargs)


async def restore_owner_checkpoint(
    runtime_label: str, state: Any, codec: Checkpoint, get_driver: Callable[[], Any],
) -> bool:
    """Restore committed tick progress at startup, before serving owner reads."""
    from _common.outbox import _check_label
    _check_label(runtime_label)
    async with get_driver().session() as session:
        row = await (await session.run(
            f"MATCH (s:{runtime_label} {{id: 'latest'}}) "
            "RETURN s.document AS document, s.last_tick_sim_time AS last_tick",
        )).single()
    if not row or not row["document"]:
        return False
    codec.restore(state, row["document"])
    if row["last_tick"]:
        state.sim_time = datetime.fromisoformat(row["last_tick"])
    return True


def catch_up_times(last: datetime | None, target: datetime, max_step_minutes: int) -> list[datetime]:
    """Split a coalesced clock gap into bounded owner ticks ending at ``target``.

    A consumer that falls behind receives only the latest SimClockTick. Applying
    a multi-hour gap as one tick moves tens of thousands of entities in a single
    transaction, which can exhaust Neo4j's shared transaction memory and then
    fail on every retry, so the owner never recovers. Bounded steps keep each
    transaction the size of a normal tick.
    """
    from datetime import timedelta
    if last is None or target <= last or max_step_minutes < 1:
        return [target]
    step = timedelta(minutes=max_step_minutes)
    times: list[datetime] = []
    cursor = last
    while target - cursor > step:
        cursor += step
        times.append(cursor)
    times.append(target)
    return times


def _in_sync(state: Any, stored_last_tick: str | None) -> bool:
    """True when ``state`` already reflects the committed checkpoint tick."""
    if not stored_last_tick:
        return False
    local = getattr(state, "last_tick_sim_time", None)
    if local is None:
        return False
    local_iso = local.isoformat() if isinstance(local, datetime) else str(local)
    return local_iso == stored_last_tick


async def run_tick(
    runtime_label: str, outbox_label: str, state: Any, codec: Checkpoint,
    get_driver: Callable[[], Any], advance: Callable[[dict, datetime], Awaitable[None]],
    payload: dict, sim_time: datetime, prepare: Callable[[Any], Awaitable[None]] | None = None,
) -> None:
    """Lock, restore, compute and persist a complete owner tick in one transaction."""
    from copy import copy, deepcopy
    from _common.outbox import stage_outbox, _check_label
    _check_label(runtime_label)
    _check_label(outbox_label)

    # Initialize separately: repeated MERGE under a held owner lock can invert
    # Neo4j's uniqueness/index locks against a concurrent command transaction.
    async with get_driver().session() as session:
        await (await session.run(f"MERGE (s:{runtime_label} {{id: 'latest'}})")).consume()

    async def apply(tx: Any) -> tuple[Any, list[dict], list[Callable[[], None]]]:
        row = await (await tx.run(
            f"MATCH (s:{runtime_label} {{id: 'latest'}}) "
            "SET s._transaction_lock = true REMOVE s._transaction_lock WITH s "
            "RETURN s.last_tick_sim_time AS last_tick, s.document AS document"
        )).single()
        candidate = copy(state)
        for key in (*codec.fields, *getattr(codec, "publish_fields", ())):
            setattr(candidate, key, deepcopy(getattr(state, key)))
        if row and row["document"] and not _in_sync(state, row["last_tick"]):
            # Only a process whose memory is not the committed checkpoint (another
            # writer, or a tick whose commit outcome was lost) needs the decode.
            # In steady state the in-memory state *is* the last committed
            # document, and re-decoding it cost a full parse per tick.
            codec.restore(candidate, row["document"])
        scope = TickScope(tx, candidate)
        token = current.set(scope)
        broadcaster = candidate.ws_broadcast
        async def defer_broadcast(message: dict) -> None:
            scope.broadcasts.append(message)
        candidate.ws_broadcast = defer_broadcast
        try:
            if prepare:
                await prepare(candidate)
            # External facts may have changed projections since this checkpoint.
            # Reconcile those inputs even when the clock itself is a replay.
            if row and row["last_tick"] and sim_time <= datetime.fromisoformat(row["last_tick"]):
                candidate.sim_time = datetime.fromisoformat(row["last_tick"])
                return candidate, [], []
            await advance(payload, sim_time)
            row = await (await tx.run(
                f"MATCH (s:{runtime_label} {{id: 'latest'}}) "
                "SET s.revision = coalesce(s.revision, 0) + 1, "
                "s.last_tick_sim_time = $ts, s.document = $document "
                "RETURN s.revision AS revision",
                ts=sim_time.isoformat(), document=codec.dump(candidate),
            )).single()
            scope.flushing = True
            await stage_outbox(tx, outbox_label, scope.facts, row["revision"])
        finally:
            candidate.ws_broadcast = broadcaster
            current.reset(token)
        return candidate, scope.broadcasts, scope.effects

    async with get_driver().session() as session:
        candidate, broadcasts, effects = await session.execute_write(apply)
    for key in (*codec.fields, *getattr(codec, "publish_fields", ()), "sim_time"):
        setattr(state, key, getattr(candidate, key))
    for effect in effects:
        effect()
    for message in broadcasts:
        if state.ws_broadcast:
            await state.ws_broadcast(message)
