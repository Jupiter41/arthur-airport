"""Create a private, consistent cold backup of this airport stack only.

Run as root on the Pi. Briefly stops airport containers, archives persistent
data and deployment sources, then restarts the stack even if archiving fails.
Contains credentials: retain the root-only directory permissions.
"""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile

ROOT = Path("/opt/arthur-airport")
DEST = Path("/var/backups/arthur-airport")
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".env.pi"),
           "-f", str(ROOT / "docker-compose.pi.yml")]


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo; backup contains private credentials")
    os.umask(0o077)
    DEST.mkdir(mode=0o700, parents=True, exist_ok=True)
    DEST.chmod(0o700)
    with (DEST / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = DEST / (stamp + ".tar")
        partial = target.with_suffix(".partial")
        ids = subprocess.check_output(COMPOSE + ["ps", "-q"], text=True).split()
        inspected = json.loads(subprocess.check_output(["docker", "inspect", *ids], text=True))
        images = {item["Name"].lstrip("/"): item["Image"] for item in inspected}
        volumes = {}
        for name in ("neo4j-data", "neo4j-logs", "kafka-data"):
            volume = "arthur-airport-pi_" + name
            info = json.loads(subprocess.check_output(["docker", "volume", "inspect", volume], text=True))[0]
            volumes[name] = Path(info["Mountpoint"])
        metrics_copy = DEST / (stamp + "-metrics.sqlite3")
        try:
            subprocess.run(COMPOSE + ["stop", "-t", "30", "sim-orchestrator"], check=True)
            subprocess.run(COMPOSE + ["stop", "-t", "30"], check=True)
            with sqlite3.connect(f"file:{ROOT}/metrics/metrics.sqlite3?mode=ro", uri=True) as source:
                with sqlite3.connect(metrics_copy) as dest:
                    source.backup(dest)
            manifest = DEST / (stamp + "-manifest.json")
            manifest.write_text(json.dumps({"created_utc": stamp, "images": images,
                                           "compose_project": "arthur-airport-pi"}, indent=2))

            def source_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
                return None if set(Path(info.name).parts) & {"node_modules", "__pycache__", ".venv", "dist", ".git"} else info

            with tarfile.open(partial, "w") as archive:
                for name, path in volumes.items():
                    archive.add(path, arcname="volumes/" + name)
                for name in ("services", "dashboards", "scripts", "config", "infra", "docs",
                             ".env.pi", "operator-credentials.txt", "docker-compose.pi.yml"):
                    archive.add(ROOT / name, arcname="deployment/" + name, filter=source_filter)
                archive.add(metrics_copy, arcname="metrics/metrics.sqlite3")
                archive.add(manifest, arcname="manifest.json")
            with tarfile.open(partial) as archive:
                assert archive.getmember("deployment/.env.pi")
                assert archive.getmember("manifest.json")
                assert archive.getmember("volumes/neo4j-data")
            partial.rename(target)
            metrics_copy.unlink()
            print(f"Verified private backup: {target} ({target.stat().st_size // 1024**2} MiB)", flush=True)
        finally:
            subprocess.run(COMPOSE + ["up", "-d", "--no-build"], check=True)


if __name__ == "__main__":
    main()
