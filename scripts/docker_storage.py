"""Local Docker builds with bounded cache and disk-space preflight (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILDER = "arthur-airport-storage-v1"
CONTAINER = f"buildx_buildkit_{BUILDER}0"
GIB = 1024 ** 3
MIN_FREE_GIB = 20


def docker(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Use argument arrays, inherit credentials, and stop on Docker errors."""
    return subprocess.run(
        ["docker", *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def default_disk_path() -> Path:
    """Check Docker Desktop's host drive, even when the checkout is elsewhere."""
    if os.name == "nt":
        candidates = [
            Path(os.environ["LOCALAPPDATA"]) / "Docker" / "wsl",
            Path.home() / "AppData" / "Local" / "Docker" / "wsl",
        ]
        # Packaged apps can redirect LOCALAPPDATA away from the actual Docker disk.
        return next((path for path in candidates if path.exists()), candidates[0])
    return Path("/var/lib/docker")


def existing_parent(path: Path) -> Path:
    path = path.expanduser().resolve()
    while not path.exists():
        path = path.parent
    return path


def require_free_space(free_bytes: int, location: str) -> None:
    print(f"{location}: {free_bytes / GIB:.1f} GiB free", flush=True)
    if free_bytes < MIN_FREE_GIB * GIB:
        raise RuntimeError(
            f"Build refused: {location} has less than {MIN_FREE_GIB} GiB free. "
            "Inspect storage first; no data has been deleted."
        )


def host_preflight(path: Path) -> None:
    volume = existing_parent(path)
    require_free_space(shutil.disk_usage(volume).free, str(volume))


def ensure_builder() -> None:
    # List first: a daemon error must never be mistaken for an absent builder.
    names = docker("buildx", "ls", "--format", "{{.Name}}", capture=True).stdout
    if BUILDER not in names.splitlines():
        docker(
            "buildx", "create", "--name", BUILDER,
            "--driver", "docker-container",
            "--driver-opt", "default-load=true",
            "--buildkitd-config", str(ROOT / "infra/docker/buildkitd.toml"),
        )
    inspection = docker("buildx", "inspect", BUILDER, capture=True).stdout
    driver = next((line.split(":", 1)[1].strip() for line in inspection.splitlines()
                   if line.startswith("Driver:")), "")
    if driver != "docker-container":
        raise RuntimeError(f"{BUILDER} is not a docker-container builder.")
    docker("buildx", "inspect", BUILDER, "--bootstrap")
    # This is the actual builder filesystem, not the checkout's filesystem.
    result = docker("exec", CONTAINER, "df", "-Pk", "/var/lib/buildkit", capture=True)
    available_kib = int(result.stdout.splitlines()[-1].split()[3])
    require_free_space(available_kib * 1024, "Docker builder filesystem")


def compose_args(profiles: list[str]) -> list[str]:
    result = ["compose", "--parallel", "1", "-f", str(ROOT / "docker-compose.yml")]
    for profile in profiles:
        result.extend(["--profile", profile])
    return result


def build(profiles: list[str], services: list[str], disk_path: Path) -> None:
    # Recheck between services to avoid starting another large build near full.
    compose = compose_args(profiles)
    config = json.loads(docker(*compose, "config", "--format", "json", capture=True).stdout)
    definitions = config["services"]
    unknown = set(services) - definitions.keys()
    if unknown:
        raise RuntimeError(f"Unknown services: {', '.join(sorted(unknown))}")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal", "--", "services", "config", "dashboards", "docker-compose.yml", "docker-compose.pi.yml", ".dockerignore", "scripts"], cwd=ROOT, text=True).strip())
    built_images: dict[str, dict[str, str]] = {}
    selected: list[str] = []

    def include(name: str) -> None:
        if name in selected:
            return
        selected.append(name)
        for dependency in definitions[name].get("depends_on", {}):
            include(dependency)

    for service in services or list(definitions):
        include(service)
    for service in selected:
        if "build" not in definitions[service]:
            continue
        host_preflight(disk_path)
        ensure_builder()
        docker(*compose, "build", "--build-arg", f"ART_REVISION={revision}",
               "--build-arg", f"ART_SOURCE_DIRTY={str(dirty).lower()}",
               "--builder", BUILDER, service)
        if (ROOT / "services" / service).is_dir() or service == "dashboard":
            image = definitions[service].get("image", f"{config['name']}-{service}")
            image_id = docker("image", "inspect", "--format", "{{.Id}}", image, capture=True).stdout.strip()
            repository = image.rsplit(":", 1)[0] if ":" in image.rsplit("/", 1)[-1] else image
            immutable = f"{repository}:{revision[:12]}-{image_id.removeprefix('sha256:')[:12]}"
            docker("image", "tag", image, immutable)
            built_images[service] = {"image": immutable, "image_id": image_id}
    if built_images:
        (ROOT / ".art-build-manifest.json").write_text(json.dumps({
            "schema_version": 1, "revision": revision, "dirty": dirty, "services": built_images,
        }, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "build", "up", "prune-cache"])
    parser.add_argument("services", nargs="*", help="Optional service names for build/up")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--disk-path", type=Path, default=default_disk_path(),
                        help="Path on Docker's host drive (override for a moved Desktop disk)")
    args = parser.parse_args()
    try:
        if args.command == "status":
            path = existing_parent(args.disk_path)
            print(f"Host free space at {path}: {shutil.disk_usage(path).free / GIB:.1f} GiB",
                  flush=True)
            docker("system", "df")
            docker("buildx", "ls")
            return 0
        docker("info", "--format", "{{.ServerVersion}}")
        if args.command == "prune-cache":
            # Explicitly scoped to this builder; never touches runtime volumes/images.
            docker("buildx", "prune", "--builder", BUILDER, "--all", "--force")
            return 0
        host_preflight(args.disk_path)
        build(args.profile, args.services, args.disk_path)
        if args.command == "up":
            host_preflight(args.disk_path)
            docker(*compose_args(args.profile), "up", "--no-build", "-d", *args.services)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Storage guard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
