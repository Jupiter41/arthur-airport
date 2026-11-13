#!/usr/bin/env python3
"""Reproduce the Git-history blast-radius counts reported in the paper.

Each upgrade is represented by its feature-introducing changeset(s) and an
explicit path scope.  The scope prevents unrelated files in mixed commits
from being attributed to the upgrade.  Counts are descriptive evidence, not
productivity measures.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Upgrade:
    name: str
    commits: tuple[str, ...]
    paths: tuple[str, ...]


UPGRADES = (
    Upgrade(
        "L1 geometry",
        ("a8db053",),
        (
            "services/sim-orchestrator/fixtures/layout.json",
            "services/sim-orchestrator/db/seed.py",
            "services/flight-service/services/spatial.py",
            "services/flight-service/services/state_machine.py",
            "services/passenger-service/services/spatial.py",
            "services/passenger-service/services/connections.py",
            "services/passenger-service/services/state_machine.py",
            "services/baggage-service/services/spatial.py",
            "services/baggage-service/services/conveyor.py",
            "tests/unit/test_*spatial.py",
            "tests/unit/test_passenger_connections.py",
        ),
    ),
    Upgrade(
        "L2 live feeds",
        ("c11ec80", "3c6f57c", "38c2399"),
        (
            "services/weather-service/services/live_metar.py",
            "services/weather-service/services/historical.py",
            "services/weather-service/routers/weather.py",
            "services/weather-service/kafka/consumer.py",
            "services/weather-service/requirements.txt",
            "services/flight-service/services/adsb.py",
            "services/flight-service/services/adsb_synthetic.py",
            "services/flight-service/routers/flights.py",
            "services/api-gateway/src/dataSources.ts",
            "services/api-gateway/src/index.ts",
            "dashboards/art-dashboard/src/pages/DataSources/*",
            "dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx",
            "dashboards/art-dashboard/src/hooks/useApi.ts",
            "docs/architecture/DATA_SOURCES.md",
            "tests/unit/test_weather_*.py",
            "docker-compose.yml",
        ),
    ),
    Upgrade(
        "BTS calibration",
        ("b6eca86",),
        (
            "services/sim-orchestrator/main.py",
            "services/sim-orchestrator/services/bts_calibration.py",
            "services/sim-orchestrator/services/passengers.py",
            "services/sim-orchestrator/services/schedule.py",
            "tests/unit/test_passenger_state_machine.py",
            "docs/architecture/DATA_SOURCES.md",
            "docs/lessons-learned/sprint-37-cost-models-capacity-planning.md",
        ),
    ),
    Upgrade(
        "L3 cost analysis",
        ("17daeb5", "22c5c18"),
        (
            "services/cost-service/*",
            "services/api-gateway/src/kafka.ts",
            "services/api-gateway/src/proxy.ts",
            "dashboards/art-dashboard/src/pages/CostDashboard/*",
            "dashboards/art-dashboard/src/stores/costStore.ts",
            "dashboards/art-dashboard/src/types.ts",
            "dashboards/art-dashboard/src/App.tsx",
            "dashboards/art-dashboard/src/components/HeaderBar.tsx",
            "dashboards/art-dashboard/src/hooks/useApi.ts",
            "dashboards/art-dashboard/src/hooks/useQueries.ts",
            "dashboards/art-dashboard/src/hooks/useWebSocket.ts",
            "docs/services/cost-service/SPEC.md",
            "docs/architecture/EVENT_BUS.md",
            "docs/architecture/DATA_MODEL.md",
            "docs/architecture/OVERVIEW.md",
            "scripts/helper_test_cost_endpoints.sh",
            "docker-compose.yml",
        ),
    ),
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def in_scope(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def component(path: str) -> str:
    parts = path.split("/")
    if parts[0] in {"services", "dashboards"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def measure(repo: Path, upgrade: Upgrade) -> tuple[int, int, int, int, int, int]:
    first_status: dict[str, str] = {}
    additions = 0
    deletions = 0

    for commit in upgrade.commits:
        parent = git(repo, "rev-parse", f"{commit}^").strip()
        status_lines = git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            parent,
            commit,
        ).splitlines()
        for line in status_lines:
            status, path = line.split("\t", 1)
            if in_scope(path, upgrade.paths):
                first_status.setdefault(path, status)

        numstat_lines = git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--numstat",
            "-r",
            "--no-renames",
            parent,
            commit,
        ).splitlines()
        for line in numstat_lines:
            added, removed, path = line.split("\t", 2)
            if in_scope(path, upgrade.paths) and added != "-":
                additions += int(added)
                deletions += int(removed)

    files = set(first_status)
    new_files = sum(status == "A" for status in first_status.values())
    existing_files = len(files) - new_files
    components = len({component(path) for path in files})
    return len(files), existing_files, new_files, components, additions, deletions


def main() -> None:
    repo = Path(
        git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip()
    )
    print("upgrade,anchors,files,existing_modified,new_files,components,insertions,deletions")
    for upgrade in UPGRADES:
        files, existing, new, components, additions, deletions = measure(repo, upgrade)
        print(
            f'"{upgrade.name}","{" ".join(upgrade.commits)}",'
            f"{files},{existing},{new},{components},{additions},{deletions}"
        )


if __name__ == "__main__":
    main()
