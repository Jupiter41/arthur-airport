"""Record installed Python runtime versions for a dependency-only security scan."""
import json
from pathlib import Path
import subprocess

root = Path("/opt/arthur-airport")
compose = ["docker", "compose", "--env-file", str(root / ".env.pi"), "-f", str(root / "docker-compose.pi.yml")]
requirements: set[str] = set()
for service in ("flight-service", "passenger-service", "baggage-service", "weather-service",
                "incident-service", "sim-orchestrator", "analysis-service", "cost-service"):
    result = subprocess.run(compose + ["exec", "-T", service, "pip", "list", "--format=json"],
                            capture_output=True, text=True, check=True, timeout=30)
    requirements.update(f"{item['name']}=={item['version']}" for item in json.loads(result.stdout))
folder = root / "audit-input"
folder.mkdir(exist_ok=True)
groups: list[dict[str, str]] = [{}]
for requirement in sorted(requirements):
    name = requirement.split("==", 1)[0].lower().replace("_", "-")
    index = 0
    while name in groups[index]:
        index += 1
        if index == len(groups):
            groups.append({})
    groups[index][name] = requirement
for path in folder.glob("requirements-*.txt"):
    path.unlink()
for index, group in enumerate(groups):
    (folder / f"requirements-{index}.txt").write_text("\n".join(group.values()) + "\n")
print(f"Recorded {len(requirements)} installed package versions; no credentials collected")
