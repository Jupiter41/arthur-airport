"""Print a credential-free deployment/metrics verification snapshot on the Pi."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess

import raspberry_monitor

root = Path("/opt/arthur-airport")
ids = subprocess.check_output(["docker", "ps", "-aq", "--filter",
                               "label=com.docker.compose.project=arthur-airport-pi"], text=True).split()
inspected = json.loads(subprocess.check_output(["docker", "inspect", *ids], text=True))
containers = []
for item in inspected:
    name = item["Config"]["Labels"]["com.docker.compose.service"]
    if name == "kafka-init":
        assert item["State"]["ExitCode"] == 0
        continue
    assert item["State"]["Status"] == "running", name
    health = item["State"].get("Health", {}).get("Status", "not-configured")
    assert health in {"healthy", "not-configured"}, (name, health)
    host = item["HostConfig"]
    assert not host.get("PortBindings"), name
    assert host["Memory"] > 0 and host["NanoCpus"] > 0, name
    assert ("traefik-public" in item["NetworkSettings"]["Networks"]) == (name == "dashboard")
    containers.append({"service": name, "health": health,
                       "memory_mib": host["Memory"] // 1024**2,
                       "cpus": host["NanoCpus"] / 1e9, "image": item["Image"]})
for name in (".env.pi", "operator-credentials.txt"):
    assert stat.S_IMODE((root / name).stat().st_mode) == 0o600, name
files = ("docker-compose.pi.yml", "services/api-gateway/src/access.ts",
         "services/api-gateway/src/kafka.ts", "services/sim-orchestrator/services/runtime_state.py",
         "dashboards/art-dashboard/src/hooks/useWebSocket.ts", "scripts/raspberry_monitor.py",
         "infra/pi/kafka-health.sh")
hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
metrics = raspberry_monitor.export(raspberry_monitor.DEFAULT_DB, 1)
latest = metrics["latest"]
report = {"containers": sorted(containers, key=lambda item: item["service"]),
          "published_ports": [], "secret_permissions": "0600", "source_sha256": hashes,
          "latest_metrics": {key: latest.get(key) for key in (
              "ts", "temperature_c", "cpu_percent", "mem_available_mib", "swap_used_mib",
              "disk_free_gib", "load_per_core", "throttled_flags", "analysis")}}
output = json.dumps(report, indent=2)
(root / "tmp-final-status.json").write_text(output)
print(output)
