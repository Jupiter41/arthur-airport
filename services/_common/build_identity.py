"""RC14 build provenance and deterministic runtime integrity (no wall clock)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

SKIP = {".git", ".venv", "__pycache__", "node_modules", "dist", "_common", "config", "data", "ml-artifacts"}


def tree_hash(root: Path, kind: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in (SKIP if kind == "python" else {"__pycache__", ".git", "node_modules"}) for part in relative.parts[:-1]):
            continue
        if kind == "python":
            include = path.suffix == ".py" or path.name.startswith("requirements") and path.suffix == ".txt"
        elif kind == "shared":
            include = path.suffix in {".py", ".mjs"}
        elif kind == "config":
            include = path.suffix in {".yaml", ".yml", ".json"}
        else:
            raise ValueError(kind)
        if include:
            digest.update((relative.as_posix() + "\0" + hashlib.sha256(path.read_bytes()).hexdigest() + "\n").encode())
    return digest.hexdigest()


def write_identity(root: Path, service: str, revision: str, dirty: bool) -> dict:
    source = tree_hash(root, "python")
    value = {"schema_version": 1, "service": service, "revision": revision, "dirty": dirty,
             "source_sha256": source, "artifact_sha256": source,
             "shared_sha256": tree_hash(root / "_common", "shared"),
             "config_sha256": tree_hash(root / "config", "config")}
    (root / "build-identity.json").write_text(json.dumps(value, sort_keys=True) + "\n")
    return value


def inspect_identity(root: Path | None = None) -> dict:
    root = root or Path(os.getenv("ART_BUILD_ROOT", "/app"))
    try:
        value = json.loads((root / "build-identity.json").read_text())
        errors = []
        if value.get("schema_version") != 1 or not value.get("revision") or value["revision"] == "unversioned":
            errors.append("unversioned build")
        for key, kind, path in (("artifact_sha256", "python", root),
                                ("shared_sha256", "shared", root / "_common"),
                                ("config_sha256", "config", root / "config")):
            if value.get(key) != tree_hash(path, kind):
                errors.append(f"{key} mismatch")
        return {**value, "integrity": not errors, "errors": errors}
    except (OSError, ValueError, KeyError, TypeError):
        return {"schema_version": 1, "service": "unknown", "revision": "unverified",
                "dirty": True, "integrity": False, "errors": ["build identity unavailable"]}


def identity_ready() -> bool:
    return inspect_identity()["integrity"] if os.getenv("ART_REQUIRE_BUILD_IDENTITY") == "1" else True


def install_build_identity(app: FastAPI, service: str) -> None:
    from pydantic import BaseModel, Field

    class BuildIdentity(BaseModel):
        schema_version: int
        service: str
        revision: str
        dirty: bool
        source_sha256: str | None = None
        artifact_sha256: str | None = None
        shared_sha256: str | None = None
        config_sha256: str | None = None
        integrity: bool
        errors: list[str] = Field(default_factory=list)

    @app.get("/build", response_model=BuildIdentity)
    async def build() -> dict:
        value = inspect_identity()
        if value["service"] not in (service, "unknown"):
            value["integrity"] = False
            value["errors"].append("service mismatch")
        return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--revision", default="unversioned")
    parser.add_argument("--dirty", default="true")
    args = parser.parse_args()
    write_identity(Path.cwd(), args.service, args.revision, args.dirty == "true")
