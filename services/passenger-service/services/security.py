"""Security throughput model — queue drain, slowdown, special assistance.

3 security checkpoints (one per terminal A, B, C).
Base throughput: 180 pax/hr/lane.
Special assistance lane: fixed 20 pax/hr, immune to congestion.
"""

import os


LANES_PER_TERMINAL = int(os.getenv("SECURITY_LANES_OPEN", "8"))
BASE_THROUGHPUT_PER_LANE = 180  # pax/hr
SA_LANE_THROUGHPUT = 20  # pax/hr — fixed, immune to congestion
SA_LANE_BREACH_THROUGHPUT = 10  # pax/hr during security_breach


class SecurityCheckpoint:
    """Per-terminal security checkpoint with main and special-assistance lanes.

    Models queue depth, throughput with congestion slowdown, and freeze
    behaviour during security breaches.
    """

    def __init__(self, terminal: str, lanes_open: int | None = None):
        self.terminal = terminal
        self.lanes_open = lanes_open or LANES_PER_TERMINAL
        self.queue: list[str] = []  # passenger IDs in main queue
        self.sa_queue: list[str] = []  # special assistance queue
        self.frozen = False  # True during security_breach

    @property
    def queue_depth(self) -> int:
        return len(self.queue)

    @property
    def sa_queue_depth(self) -> int:
        return len(self.sa_queue)

    def effective_throughput(self, forecast_queue: int) -> float:
        """Compute effective throughput per hour with slowdown."""
        base = self.lanes_open * BASE_THROUGHPUT_PER_LANE
        if self.frozen:
            return 0.0
        actual = self.queue_depth
        if forecast_queue > 0 and actual > forecast_queue * 1.3:
            slowdown = min(1.0, forecast_queue / actual)
            # Floor: never drop below 50% of base throughput
            slowdown = max(0.5, slowdown)
            return base * slowdown
        return float(base)

    def sa_throughput(self) -> float:
        """Special assistance lane throughput."""
        if self.frozen:
            return float(SA_LANE_BREACH_THROUGHPUT)
        return float(SA_LANE_THROUGHPUT)

    def wait_minutes(self, forecast_queue: int) -> float:
        """Estimated wait time in minutes for the main queue."""
        throughput = self.effective_throughput(forecast_queue)
        if throughput <= 0:
            return 999.0
        return (self.queue_depth / throughput) * 60.0

    def drain_per_tick(self, forecast_queue: int, delta_minutes: int = 1) -> int:
        """How many passengers to drain from main queue this tick.

        ``delta_minutes`` accounts for multi-minute ticks at high sim speeds:
        the throughput is ``effective / 60 * delta`` so that skipped ticks
        don't reduce overall security capacity.
        """
        if self.frozen:
            return 0
        throughput = self.effective_throughput(forecast_queue)
        drain = max(0, int(throughput / 60 * delta_minutes))
        # Guard: always drain at least 1 pax/tick if queue > 0
        if drain == 0 and self.queue_depth > 0:
            drain = 1
        return drain

    def sa_drain_per_tick(self, delta_minutes: int = 1) -> int:
        """How many SA passengers to drain per tick."""
        throughput = self.sa_throughput()
        # 20 pax/hr = 0.33/min — at least 1 every 3 ticks at normal speed
        return max(0, int(throughput / 60 * delta_minutes))

    def enqueue(self, passenger_id: str, special_assistance: bool = False) -> None:
        """Add passenger to the appropriate queue."""
        if special_assistance:
            if passenger_id not in self.sa_queue:
                self.sa_queue.append(passenger_id)
        else:
            if passenger_id not in self.queue:
                self.queue.append(passenger_id)

    def drain(self, forecast_queue: int, delta_minutes: int = 1) -> tuple[list[str], list[str]]:
        """Drain passengers through security. Returns (main_drained, sa_drained)."""
        # Main queue
        main_count = self.drain_per_tick(forecast_queue, delta_minutes)
        main_drained = self.queue[:main_count]
        self.queue = self.queue[main_count:]

        # SA queue — drain at SA rate, minimum 1 every 3 minutes
        sa_count = self.sa_drain_per_tick(delta_minutes)
        # Ensure at least 1 SA pax processed every 3 ticks
        if sa_count == 0 and self.sa_queue:
            sa_count = 1  # fractional throughput: process 1 pax
        sa_drained = self.sa_queue[:sa_count]
        self.sa_queue = self.sa_queue[sa_count:]

        return main_drained, sa_drained

    def freeze(self) -> None:
        """Freeze main lanes (security breach). SA lane stays at reduced capacity."""
        self.frozen = True

    def unfreeze(self) -> None:
        """Resume normal operations."""
        self.frozen = False


class SecuritySystem:
    """Manages all 3 terminal security checkpoints (A, B, C).

    Provides unified enqueue, drain, freeze/unfreeze, and summary APIs.
    """

    def __init__(self):
        self.checkpoints: dict[str, SecurityCheckpoint] = {
            "A": SecurityCheckpoint("A"),
            "B": SecurityCheckpoint("B"),
            "C": SecurityCheckpoint("C"),
        }

    def get(self, terminal: str) -> SecurityCheckpoint:
        return self.checkpoints[terminal]

    def enqueue(self, terminal: str, passenger_id: str, special_assistance: bool = False) -> None:
        self.checkpoints[terminal].enqueue(passenger_id, special_assistance)

    def drain_all(self, forecast_queues: dict[str, int], delta_minutes: int = 1) -> dict[str, tuple[list[str], list[str]]]:
        """Drain all checkpoints. Returns {terminal: (main_drained, sa_drained)}."""
        result = {}
        for terminal, cp in self.checkpoints.items():
            forecast = forecast_queues.get(terminal, 0)
            result[terminal] = cp.drain(forecast, delta_minutes)
        return result

    def freeze_terminal(self, terminal: str) -> None:
        if terminal in self.checkpoints:
            self.checkpoints[terminal].freeze()

    def unfreeze_terminal(self, terminal: str) -> None:
        if terminal in self.checkpoints:
            self.checkpoints[terminal].unfreeze()

    def get_summary(self, forecast_queues: dict[str, int]) -> dict[str, dict]:
        """Summary for REST API."""
        summary = {}
        for terminal, cp in self.checkpoints.items():
            forecast = forecast_queues.get(terminal, 0)
            summary[f"terminal_{terminal.lower()}"] = {
                "queue_depth": cp.queue_depth,
                "wait_minutes": round(cp.wait_minutes(forecast), 1),
                "lanes_open": cp.lanes_open,
            }
        return summary
