"""Scenario engine — loads YAML definitions, schedules events, collects metrics, evaluates outcomes."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from kafka.producer import emit_inject_incident
from models.scenario import (
    ExpectedOutcome,
    MetricSnapshot,
    OutcomeResult,
    ScenarioDefinition,
    ScenarioRunResult,
    ScenarioRunStatus,
)

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(os.getenv("SCENARIOS_DIR", "/app/scenarios/definitions"))
SCENARIOS_USER_DIR = Path(os.getenv("SCENARIOS_USER_DIR", "/app/scenarios/user"))
RESULTS_DIR = Path(os.getenv("SCENARIO_RESULTS_DIR", "/app/scenarios/results"))

# Metric snapshot interval (every N sim-minutes)
SNAPSHOT_INTERVAL = int(os.getenv("SCENARIO_SNAPSHOT_INTERVAL", "5"))


class ScenarioEngine:
    """Manages loading, running, and evaluating simulation scenarios.

    Only one scenario can be active at a time. The engine integrates with the
    clock loop via the ``on_tick`` method which must be called every sim-minute.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, ScenarioDefinition] = {}
        self._definition_meta: dict[str, dict] = {}
        self._active_run: ScenarioRunResult | None = None
        self._active_def: ScenarioDefinition | None = None
        self._scenario_start_sim_time: datetime | None = None
        self._pending_events: list[dict] = []
        self._peak_metrics: dict[str, float] = {}
        self._past_results: list[ScenarioRunResult] = []

    # ── Loading ───────────────────────────────────────────────────

    def load_definitions(self) -> int:
        """Scan the definitions directory and load all valid YAML scenarios.

        Returns the number of successfully loaded scenarios.
        """
        self._definitions.clear()
        self._definition_meta.clear()

        count = 0
        count += self._load_from_dir(SCENARIOS_DIR, is_base=True)
        count += self._load_from_dir(SCENARIOS_USER_DIR, is_base=False)

        logger.info("Loaded %d scenario definitions", count)
        return count

    def _load_from_dir(self, directory: Path, is_base: bool) -> int:
        """Load scenario YAML files from one directory into memory."""
        if not directory.exists():
            if is_base:
                logger.warning("Scenarios directory not found: %s", directory)
            return 0

        count = 0
        for path in sorted(directory.glob("*.yaml")):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = yaml.safe_load(f)
                defn = ScenarioDefinition.model_validate(raw)

                if defn.name in self._definitions:
                    logger.error(
                        "Skipping duplicate scenario name '%s' in %s",
                        defn.name,
                        path,
                    )
                    continue

                self._definitions[defn.name] = defn
                self._definition_meta[defn.name] = {
                    "is_base": is_base,
                    "file_path": path,
                }
                count += 1
                logger.info("Loaded scenario: %s", defn.name)
            except Exception as e:
                logger.error("Failed to load scenario %s: %s", path.name, e)

        return count

    def list_scenarios(self) -> list[dict]:
        """Return a summary list of all loaded scenario definitions."""
        scenarios = [
            {
                "name": d.name,
                "description": d.description,
                "duration_sim_minutes": d.duration_sim_minutes,
                "event_count": len(d.events),
                "outcome_count": len(d.expected_outcomes),
                "is_base": self.is_base(d.name),
            }
            for d in self._definitions.values()
        ]
        scenarios.sort(key=lambda item: (item["is_base"] is False, item["name"].lower()))
        return scenarios

    def get_definition(self, name: str) -> ScenarioDefinition | None:
        return self._definitions.get(name)

    def get_definition_payload(self, name: str) -> dict | None:
        """Return scenario definition with metadata used by API clients."""
        defn = self._definitions.get(name)
        if defn is None:
            return None
        payload = defn.model_dump(mode="json")
        payload["is_base"] = self.is_base(name)
        return payload

    def is_base(self, name: str) -> bool:
        return bool(self._definition_meta.get(name, {}).get("is_base", False))

    def create_definition(self, definition: ScenarioDefinition) -> ScenarioDefinition:
        """Create a new custom scenario definition."""
        if definition.name in self._definitions:
            raise ValueError(f"Scenario '{definition.name}' already exists")

        file_path = self._allocate_user_file_path(definition.name)
        self._write_definition_yaml(file_path, definition)

        self._definitions[definition.name] = definition
        self._definition_meta[definition.name] = {
            "is_base": False,
            "file_path": file_path,
        }
        return definition

    def update_definition(self, current_name: str, definition: ScenarioDefinition) -> ScenarioDefinition:
        """Update an existing custom scenario (optionally rename)."""
        existing = self._definitions.get(current_name)
        if existing is None:
            raise KeyError(f"Scenario '{current_name}' not found")
        if self.is_base(current_name):
            raise PermissionError("Base scenarios are immutable")

        if self.is_active() and self._active_run and self._active_run.scenario_name == current_name:
            raise RuntimeError("Cannot update a scenario while it is running")

        target_name = definition.name
        if target_name != current_name and target_name in self._definitions:
            raise ValueError(f"Scenario '{target_name}' already exists")

        old_file_path: Path | None = self._definition_meta.get(current_name, {}).get("file_path")
        new_file_path = self._allocate_user_file_path(target_name)
        if target_name == current_name and old_file_path is not None:
            new_file_path = old_file_path

        self._write_definition_yaml(new_file_path, definition)

        if old_file_path is not None and old_file_path != new_file_path and old_file_path.exists():
            old_file_path.unlink()

        if target_name != current_name:
            self._definitions.pop(current_name, None)
            self._definition_meta.pop(current_name, None)

        self._definitions[target_name] = definition
        self._definition_meta[target_name] = {
            "is_base": False,
            "file_path": new_file_path,
        }
        return definition

    def delete_definition(self, name: str) -> None:
        """Delete one custom scenario definition."""
        if name not in self._definitions:
            raise KeyError(f"Scenario '{name}' not found")
        if self.is_base(name):
            raise PermissionError("Base scenarios are immutable")

        if self.is_active() and self._active_run and self._active_run.scenario_name == name:
            raise RuntimeError("Cannot delete a scenario while it is running")

        file_path: Path | None = self._definition_meta.get(name, {}).get("file_path")
        if file_path is not None and file_path.exists():
            file_path.unlink()

        self._definitions.pop(name, None)
        self._definition_meta.pop(name, None)

    def fork_definition(self, source_name: str, target_name: str) -> ScenarioDefinition:
        """Clone an existing scenario to a new custom scenario name."""
        source = self._definitions.get(source_name)
        if source is None:
            raise KeyError(f"Scenario '{source_name}' not found")
        if target_name in self._definitions:
            raise ValueError(f"Scenario '{target_name}' already exists")

        cloned_payload = source.model_dump(mode="json")
        cloned_payload["name"] = target_name
        cloned = ScenarioDefinition.model_validate(cloned_payload)
        return self.create_definition(cloned)

    def _allocate_user_file_path(self, scenario_name: str) -> Path:
        """Create a deterministic user scenario filepath with conflict handling."""
        SCENARIOS_USER_DIR.mkdir(parents=True, exist_ok=True)
        slug = self._slugify_name(scenario_name)
        candidate = SCENARIOS_USER_DIR / f"{slug}.yaml"
        idx = 2
        while candidate.exists():
            candidate = SCENARIOS_USER_DIR / f"{slug}-{idx}.yaml"
            idx += 1
        return candidate

    @staticmethod
    def _slugify_name(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return slug or "scenario"

    @staticmethod
    def _write_definition_yaml(path: Path, definition: ScenarioDefinition) -> None:
        payload = definition.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=False)

    # ── Run lifecycle ─────────────────────────────────────────────

    def is_active(self) -> bool:
        return self._active_run is not None and self._active_run.status == ScenarioRunStatus.RUNNING

    def get_active_run(self) -> ScenarioRunResult | None:
        return self._active_run

    def start_run(self, name: str, sim_time: datetime) -> ScenarioRunResult:
        """Begin a new scenario run. Raises ValueError if already active or name unknown."""
        if self.is_active():
            raise ValueError("A scenario is already running")

        defn = self._definitions.get(name)
        if defn is None:
            raise ValueError(f"Unknown scenario: {name}")

        run_id = str(uuid4())[:8]
        self._active_def = defn
        self._scenario_start_sim_time = sim_time
        self._pending_events = [
            {
                "offset": e.at_sim_offset_minutes,
                "type": e.type.value,
                "severity": e.severity.value,
                "location": e.location,
                "trigger": e.trigger,
                "description": e.description,
                "fired": False,
            }
            for e in defn.events
        ]
        self._peak_metrics = {}

        self._active_run = ScenarioRunResult(
            run_id=run_id,
            scenario_name=name,
            status=ScenarioRunStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
            sim_start_time=sim_time.isoformat(),
            duration_sim_minutes=defn.duration_sim_minutes,
        )
        logger.info("Scenario '%s' started (run_id=%s, duration=%d min)",
                     name, run_id, defn.duration_sim_minutes)
        return self._active_run

    def stop_run(self) -> ScenarioRunResult | None:
        """Manually stop an active run."""
        if self._active_run is None:
            return None
        self._active_run.status = ScenarioRunStatus.STOPPED
        self._active_run.completed_at = datetime.now(timezone.utc).isoformat()
        result = self._active_run
        self._finalize_run(result)
        return result

    # ── Tick handler ──────────────────────────────────────────────

    async def on_tick(self, sim_time: datetime) -> None:
        """Called every sim-minute by the clock loop. Fires scheduled events and collects metrics."""
        if not self.is_active() or self._scenario_start_sim_time is None:
            return

        offset = int((sim_time - self._scenario_start_sim_time).total_seconds() / 60)

        # Fire any due events
        for event in self._pending_events:
            if not event["fired"] and event["offset"] <= offset:
                event["fired"] = True
                logger.info("Scenario event at offset %d: %s (%s @ %s)",
                            event["offset"], event["type"], event["severity"], event["location"])
                emit_inject_incident(
                    sim_time=sim_time,
                    incident_type=event["type"],
                    severity=event["severity"],
                    location=event["location"],
                    trigger=event["trigger"],
                    description=event.get("description"),
                )
                self._active_run.events_injected += 1

        # Periodic metric snapshot
        if offset % SNAPSHOT_INTERVAL == 0:
            snapshot = await self._collect_metrics(sim_time, offset)
            self._active_run.metric_snapshots.append(snapshot)
            self._update_peaks(snapshot)

        # Check if duration elapsed
        if offset >= self._active_def.duration_sim_minutes:
            await self._complete_run(sim_time)

    # ── Metrics collection ────────────────────────────────────────

    async def _collect_metrics(self, sim_time: datetime, offset: int) -> MetricSnapshot:
        """Query Neo4j for current simulation metrics."""
        from db.neo4j import get_driver

        snapshot = MetricSnapshot(
            sim_time=sim_time.isoformat(),
            offset_minutes=offset,
        )

        try:
            driver = get_driver()
            async with driver.session() as session:
                # Flights delayed
                result = await session.run(
                    "MATCH (f:Flight) WHERE f.delay_minutes > 0 AND f.status <> 'cancelled' "
                    "RETURN count(f) AS cnt, coalesce(avg(f.delay_minutes), 0) AS avg_delay, "
                    "coalesce(sum(f.delay_minutes), 0) AS total_delay"
                )
                rec = await result.single()
                if rec:
                    snapshot.flights_delayed_current = rec["cnt"]
                    snapshot.avg_delay_minutes = round(float(rec["avg_delay"]), 1)
                    snapshot.total_delay_minutes = int(rec["total_delay"])

                # Cancelled flights
                result = await session.run(
                    "MATCH (f:Flight {status: 'cancelled'}) RETURN count(f) AS cnt"
                )
                rec = await result.single()
                if rec:
                    snapshot.flights_cancelled = rec["cnt"]

                # Holding stack (approach + delayed)
                result = await session.run(
                    "MATCH (f:Flight) WHERE f.status = 'approach' AND f.delay_minutes > 0 "
                    "RETURN count(f) AS cnt"
                )
                rec = await result.single()
                if rec:
                    snapshot.holding_stack_depth = rec["cnt"]

                # Active incidents
                result = await session.run(
                    "MATCH (i:Incident) WHERE i.status = 'active' RETURN count(i) AS cnt"
                )
                rec = await result.single()
                if rec:
                    snapshot.incident_count_active = rec["cnt"]

                # Cascade depth (max chain length)
                result = await session.run(
                    "MATCH path = (root:Incident)-[:SPAWNED*1..5]->(child:Incident) "
                    "RETURN max(length(path)) AS max_depth"
                )
                rec = await result.single()
                if rec and rec["max_depth"] is not None:
                    snapshot.cascade_depth_max = int(rec["max_depth"])

                # Missed connections
                result = await session.run(
                    "MATCH (p:Passenger) WHERE p.status = 'missed_connection' "
                    "RETURN count(p) AS cnt"
                )
                rec = await result.single()
                if rec:
                    snapshot.missed_connections = rec["cnt"]

                # Disrupted passengers (missed_connection, rebooked, stranded)
                result = await session.run(
                    "MATCH (p:Passenger) WHERE p.status IN "
                    "['missed_connection', 'rebooked', 'stranded', 'cancelled'] "
                    "RETURN count(p) AS cnt"
                )
                rec = await result.single()
                if rec:
                    snapshot.pax_disrupted = rec["cnt"]

        except Exception as e:
            logger.error("Error collecting scenario metrics: %s", e)

        return snapshot

    def _update_peaks(self, snapshot: MetricSnapshot) -> None:
        """Track peak values seen during the run for outcome evaluation."""
        for field_name in snapshot.model_fields:
            if field_name in ("sim_time", "offset_minutes"):
                continue
            val = getattr(snapshot, field_name)
            if isinstance(val, (int, float)):
                key = field_name
                if key not in self._peak_metrics or val > self._peak_metrics[key]:
                    self._peak_metrics[key] = val

    # ── Outcome evaluation ────────────────────────────────────────

    def _evaluate_outcomes(self) -> list[OutcomeResult]:
        """Check each expected outcome against collected metric history."""
        results: list[OutcomeResult] = []

        if self._active_def is None:
            return results

        for outcome in self._active_def.expected_outcomes:
            result = self._evaluate_single_outcome(outcome)
            results.append(result)

        return results

    def _evaluate_single_outcome(self, outcome: ExpectedOutcome) -> OutcomeResult:
        """Evaluate a single outcome assertion against the metric snapshot history.

        The assertion passes if the condition was met in ANY snapshot taken within
        the specified time window from scenario start.
        """
        # Parse condition: ">= 10", "< 5", "== 3"
        match = re.match(r"(>=|<=|>|<|==)\s*(\d+(?:\.\d+)?)", outcome.condition.strip())
        if not match:
            return OutcomeResult(
                metric=outcome.metric,
                condition=outcome.condition,
                expected=outcome.condition,
                actual=0.0,
                passed=False,
                evaluated_at_offset_minutes=0,
            )

        operator = match.group(1)
        threshold = float(match.group(2))

        # Find the best (highest or lowest depending on operator) value
        # within the time window
        best_val = 0.0
        best_offset = 0
        passed = False

        for snap in (self._active_run.metric_snapshots if self._active_run else []):
            if snap.offset_minutes > outcome.within_sim_minutes:
                continue

            val = getattr(snap, outcome.metric, None)
            if val is None:
                continue

            val = float(val)

            if _check_condition(val, operator, threshold):
                passed = True
                best_val = val
                best_offset = snap.offset_minutes
                break  # first match is enough

            if val > best_val:
                best_val = val
                best_offset = snap.offset_minutes

        return OutcomeResult(
            metric=outcome.metric,
            condition=outcome.condition,
            expected=outcome.condition,
            actual=best_val,
            passed=passed,
            evaluated_at_offset_minutes=best_offset,
        )

    # ── Run completion ────────────────────────────────────────────

    async def _complete_run(self, sim_time: datetime) -> None:
        """Finalize the run: evaluate outcomes, write results."""
        if self._active_run is None:
            return

        # Take one final snapshot
        duration = self._active_def.duration_sim_minutes if self._active_def else 0
        final_snap = await self._collect_metrics(sim_time, duration)
        self._active_run.metric_snapshots.append(final_snap)
        self._update_peaks(final_snap)

        self._active_run.status = ScenarioRunStatus.COMPLETED
        self._active_run.completed_at = datetime.now(timezone.utc).isoformat()
        self._active_run.sim_end_time = sim_time.isoformat()

        # Evaluate outcomes
        self._active_run.outcome_results = self._evaluate_outcomes()
        self._active_run.passed = all(r.passed for r in self._active_run.outcome_results)

        # Generate summary
        total = len(self._active_run.outcome_results)
        passes = sum(1 for r in self._active_run.outcome_results if r.passed)
        self._active_run.summary = (
            f"Scenario '{self._active_run.scenario_name}': "
            f"{passes}/{total} outcomes passed. "
            f"{self._active_run.events_injected} events injected. "
            f"{'PASS' if self._active_run.passed else 'FAIL'}"
        )

        self._finalize_run(self._active_run)
        logger.info("Scenario completed: %s", self._active_run.summary)

    def _finalize_run(self, run: ScenarioRunResult) -> None:
        """Persist results to disk and archive the run."""
        self._past_results.append(run)
        self._write_results(run)
        self._active_run = None
        self._active_def = None
        self._scenario_start_sim_time = None
        self._pending_events = []
        self._peak_metrics = {}

    def _write_results(self, run: ScenarioRunResult) -> None:
        """Write run results to the results directory."""
        run_dir = RESULTS_DIR / run.scenario_name / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # metrics.json
        metrics_path = run_dir / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(
                [s.model_dump() for s in run.metric_snapshots],
                f, indent=2,
            )

        # result.json (full run)
        result_path = run_dir / "result.json"
        with open(result_path, "w") as f:
            json.dump(run.model_dump(), f, indent=2)

        # report.md (human-readable)
        report_path = run_dir / "report.md"
        with open(report_path, "w") as f:
            f.write(self._generate_report(run))

        logger.info("Results written to %s", run_dir)

    def _generate_report(self, run: ScenarioRunResult) -> str:
        """Generate a markdown report for the scenario run."""
        lines = [
            f"# Scenario Report: {run.scenario_name}",
            "",
            f"**Run ID:** {run.run_id}",
            f"**Status:** {run.status.value}",
            f"**Result:** {'PASS' if run.passed else 'FAIL'}",
            f"**Started:** {run.started_at}",
            f"**Completed:** {run.completed_at}",
            f"**Sim time:** {run.sim_start_time} → {run.sim_end_time}",
            f"**Duration:** {run.duration_sim_minutes} sim-minutes",
            f"**Events injected:** {run.events_injected}",
            "",
            "---",
            "",
            "## Outcome Results",
            "",
            "| Metric | Condition | Actual | Passed |",
            "|--------|-----------|--------|--------|",
        ]

        for o in run.outcome_results:
            check = "PASS" if o.passed else "FAIL"
            lines.append(f"| {o.metric} | {o.condition} | {o.actual} | {check} |")

        if run.metric_snapshots:
            lines.extend([
                "",
                "---",
                "",
                "## Peak Metrics",
                "",
            ])
            # Show peak values from last snapshot or peak tracking
            last = run.metric_snapshots[-1]
            for field_name in last.model_fields:
                if field_name in ("sim_time", "offset_minutes"):
                    continue
                val = getattr(last, field_name)
                lines.append(f"- **{field_name}:** {val}")

        lines.append("")
        return "\n".join(lines)

    # ── Past results ──────────────────────────────────────────────

    def get_past_results(self) -> list[dict]:
        """Return summaries of all past runs."""
        return [
            {
                "run_id": r.run_id,
                "scenario_name": r.scenario_name,
                "status": r.status.value,
                "passed": r.passed,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "events_injected": r.events_injected,
                "summary": r.summary,
            }
            for r in self._past_results
        ]

    def get_result(self, run_id: str) -> ScenarioRunResult | None:
        for r in self._past_results:
            if r.run_id == run_id:
                return r
        return None


def _check_condition(value: float, operator: str, threshold: float) -> bool:
    """Evaluate a comparison condition."""
    match operator:
        case ">=":
            return value >= threshold
        case "<=":
            return value <= threshold
        case ">":
            return value > threshold
        case "<":
            return value < threshold
        case "==":
            return value == threshold
        case _:
            return False


# Module-level singleton
_engine = ScenarioEngine()


def get_engine() -> ScenarioEngine:
    return _engine
