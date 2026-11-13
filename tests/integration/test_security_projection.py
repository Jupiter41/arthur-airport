"""Rebuild analysis queues from real passenger-owned Neo4j observations."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
PASSENGER = os.getenv("PASSENGER_SVC_URL", "http://localhost:8002")

WORKER = r'''
import asyncio, json
from datetime import datetime, timezone
from db.neo4j import wait_for_neo4j, close_neo4j, load_operational_projection
from services.state import OperationalState

async def main():
    await wait_for_neo4j(max_attempts=1)
    try:
        snapshot = await load_operational_projection()
        assert len(snapshot['security']) == 3, snapshot['security']
        state = OperationalState()
        state.restore_graph(snapshot)
        assert state.sim_time is None
        for row in snapshot['security']:
            observation = row['checkpoint']
            key = 'Terminal ' + observation['terminal'].removeprefix('Terminal ')
            security = state.security[key]
            assert security.queue_depth == observation['queue_depth']
            assert security.open_lanes == observation['lanes_open']
            assert security.observed_wait_minutes == observation['wait_minutes']
            at = datetime.fromisoformat(observation['at'])
            at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
            assert security.last_updated == at
            assert security.forecast_confidence == 0
        print('Recovered all three measured security checkpoints without a tick')
    finally:
        await close_neo4j()

asyncio.run(main())
'''


def test_fresh_analysis_process_restores_real_owner_observations():
    try:
        requests.get(f"{PASSENGER}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Passenger service unavailable: {exc}")
        pytest.skip("Live digital twin not running")
    result = subprocess.run(
        ["docker", "compose", "run", "--rm", "-T", "--no-deps",
         "analysis-service", "python", "-c", WORKER],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Recovered all three" in result.stdout
