"""Host resource guard. Freezes only the airport clock when pressure is unsafe.

Install as the supplied systemd timer. Recovery is explicit after inspection;
never auto-restart a simulation that exhausted its capacity budget.
"""
from pathlib import Path
import json
import shutil
import subprocess

ROOT = Path("/opt/arthur-airport")
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".env.pi"),
           "-f", str(ROOT / "docker-compose.pi.yml")]


def reasons() -> list[str]:
    mem = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available_kib = int(mem["MemAvailable"].split()[0])
    result = []
    if available_kib < 450 * 1024:
        result.append(f"available RAM {available_kib // 1024} MiB < 450 MiB")
    if shutil.disk_usage(ROOT).free < 5 * 1024**3:
        result.append("free disk below 5 GiB")
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists() and int(thermal.read_text()) > 80_000:
        result.append("CPU temperature above 80 C")
    # Growth bound until archived entity retention is implemented. Do not silently
    # delete graph entities or change historical simulation results.
    for volume in ("arthur-airport-pi_neo4j-data", "arthur-airport-pi_kafka-data"):
        info = subprocess.run(["docker", "volume", "inspect", volume], capture_output=True, text=True)
        if info.returncode == 0:
            mount = json.loads(info.stdout)[0]["Mountpoint"]
            size = subprocess.run(["du", "-sm", mount], capture_output=True, text=True)
            if size.returncode == 0 and int(size.stdout.split()[0]) > 2048:
                result.append(f"{volume} exceeds 2 GiB safety budget")
    return result


if __name__ == "__main__":
    unsafe = reasons()
    if unsafe:
        print("Airport resource guard: " + "; ".join(unsafe), flush=True)
        state = subprocess.run(COMPOSE + ["ps", "--all", "--format", "json", "sim-orchestrator"],
                               capture_output=True, text=True, check=True)
        if '"paused"' not in state.stdout:
            subprocess.run(COMPOSE + ["pause", "sim-orchestrator"], cwd=ROOT, check=True)
