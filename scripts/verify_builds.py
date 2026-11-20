"""Fail-closed deployed build/contract verification, including frontend artifacts."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_identity_tool", ROOT / "services/_common/build_identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
SERVICES = {"flight-service": 8001, "passenger-service": 8002, "baggage-service": 8003,
            "weather-service": 8004, "incident-service": 8005, "sim-orchestrator": 8006,
            "analysis-service": 8007, "cost-service": 8008, "planning-service": 8009,
            "api-gateway": 3000, "dashboard": 5173}


def verify(project: str, manifest: dict, revision: str) -> dict:
    shared = identity.tree_hash(ROOT / "services/_common", "shared")
    config = identity.tree_hash(ROOT / "config", "config")
    reports = {}
    node = shutil.which("node") or str(Path.home() / ".nvm/versions/node/v24.13.0/bin/node")
    for service, port in SERVICES.items():
        errors = []
        value = None
        image_id = None
        try:
            base = f"http://localhost:{port}"
            response = requests.get(base + ("/build.json" if service == "dashboard" else "/build"), timeout=5)
            response.raise_for_status()
            value = response.json()
            for key, expected in (("schema_version", 1), ("service", service), ("revision", revision),
                                  ("dirty", False), ("shared_sha256", shared), ("config_sha256", config)):
                if value.get(key) != expected:
                    errors.append(f"{key} mismatch")
            root = ROOT / ("dashboards/art-dashboard" if service == "dashboard" else f"services/{service}")
            if service in {"api-gateway", "dashboard"}:
                source = subprocess.check_output([node, str(ROOT / "services/_common/build_identity.mjs"), "--source", str(root)], text=True)
            else:
                source = identity.tree_hash(root, "python")
            if value.get("source_sha256") != source:
                errors.append("checkout source mismatch")
            if service == "dashboard":
                digest = hashlib.sha256()
                assets = value.get("artifact_files")
                if not isinstance(assets, dict) or not assets or len(assets) > 1024:
                    raise ValueError("invalid frontend artifact inventory")
                for name, expected in sorted(assets.items()):
                    if not isinstance(name, str) or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                        raise ValueError("invalid frontend artifact path")
                    asset = requests.get(base + "/" + quote(name, safe="/"), timeout=5)
                    asset.raise_for_status()
                    actual = hashlib.sha256(asset.content).hexdigest()
                    if actual != expected:
                        errors.append(f"frontend asset mismatch: {name}")
                    digest.update((name + "\0" + actual + "\n").encode())
                if digest.hexdigest() != value.get("artifact_sha256"):
                    errors.append("frontend artifact tree mismatch")
            elif value.get("integrity") is not True:
                errors.append("runtime integrity failed")
            container = json.loads(subprocess.check_output(["docker", "inspect", f"{project}-{service}-1"]))[0]
            image_id = container["Image"]
            expected_image = manifest["services"][service]["image_id"]
            if image_id != expected_image:
                errors.append("deployment lock image mismatch")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, requests.RequestException) as error:
            errors.append(str(error))
        reports[service] = {"verified": not errors, "errors": errors, "image_id": image_id, "build": value}
    return {"verified": all(row["verified"] for row in reports.values()), "revision": revision, "services": reports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / ".art-build-manifest.json")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    revision = args.revision or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = verify(args.project, json.loads(args.manifest.read_text()), revision)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"verified": report["verified"], "services": {name: row["verified"] for name, row in report["services"].items()}}))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
