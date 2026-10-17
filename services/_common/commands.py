"""Shared command mapping and receipt lifecycle; no service imports or I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable
from datetime import datetime


@dataclass(frozen=True)
class CommandIntent:
    topic: str
    command_type: str
    payload: dict
    entity_key: str


def action_command(action_type: str, parameters: dict) -> CommandIntent | None:
    """Resolve only actions with concrete, validated execution parameters."""

    def text(key: str) -> str | None:
        value = parameters.get(key)
        return value if isinstance(value, str) and value.strip() else None

    flight_id = text("flight_id") or text("outbound_flight")
    if action_type == "reassign_gate" and flight_id and text("gate_id"):
        return CommandIntent(
            "flights.commands",
            "ReassignGate",
            {
                "flight_id": flight_id,
                "gate_id": parameters["gate_id"],
            },
            flight_id,
        )
    if action_type in {"hold_connecting_flight", "delay_taxi"} and flight_id:
        duration = parameters.get("duration_min", parameters.get("hold_minutes"))
        if type(duration) is int and duration > 0:
            return CommandIntent(
                "flights.commands",
                "HoldFlight",
                {
                    "flight_id": flight_id,
                    "duration_min": duration,
                    "reason": text("reason") or action_type,
                },
                flight_id,
            )
    if action_type == "open_security_lane" and text("terminal"):
        lanes = parameters.get("lanes_open", parameters.get("new_lane_count"))
        terminal = parameters["terminal"].removeprefix("Terminal ")
        if type(lanes) is int and 1 <= lanes <= 20:
            return CommandIntent(
                "passengers.commands",
                "OpenSecurityLane",
                {
                    "terminal": terminal,
                    "lanes_open": lanes,
                },
                terminal,
            )
    if (
        action_type == "redirect_baggage"
        and text("bag_id")
        and text("target_flight_id")
    ):
        return CommandIntent(
            "baggage.commands",
            "RedirectBaggage",
            {
                "bag_id": parameters["bag_id"],
                "target_flight_id": parameters["target_flight_id"],
            },
            parameters["bag_id"],
        )
    return None


class CommandReceipts:
    """Remember completed results so redelivery re-emits a receipt, not a mutation.

    This is bounded process-local deduplication, not a transactional outbox.
    Exceptions are retryable; commands are never remembered before execution.
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self.results: dict[str, tuple[str, dict]] = {}
        self.max_size = max_size

    async def handle(
        self,
        envelope: dict,
        sim_time: datetime | None,
        execute: Callable[[dict], Awaitable[str | None]],
        emit: Callable[[str, datetime, dict, str], None],
        load: Callable[[str], Awaitable[tuple[str, dict] | None]] | None = None,
        save: Callable[[str, tuple[str, dict]], Awaitable[None]] | None = None,
    ) -> None:
        command_id = envelope.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("command_id is required")
        if sim_time is None:
            raise RuntimeError("Simulation clock not available")
        receipt = self.results.get(command_id)
        if receipt is None and load is not None:
            receipt = await load(command_id)
        if receipt is None:
            reason = await execute(envelope)
            receipt = (
                "CommandRejected" if reason else "CommandExecuted",
                {
                    "command_id": command_id,
                    "command_type": envelope.get("command_type"),
                    "reason": reason,
                },
            )
            if save is not None:
                await save(command_id, receipt)
        self.results[command_id] = receipt
        if len(self.results) > self.max_size:
            del self.results[next(iter(self.results))]
        event_type, payload = receipt
        emit(event_type, sim_time, payload, command_id)
