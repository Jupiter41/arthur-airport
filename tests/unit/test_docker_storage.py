"""The disk guard must fail before builds/start and scope all cleanup."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location(
    "docker_storage", Path(__file__).resolve().parents[2] / "scripts/docker_storage.py",
)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


def test_low_space_refuses_build_and_start(monkeypatch):
    docker = Mock()
    monkeypatch.setattr(storage, "docker", docker)
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda _: Mock(free=19 * storage.GIB))
    monkeypatch.setattr(sys, "argv", ["docker_storage.py", "up"])
    assert storage.main() == 1
    assert docker.call_args_list == [(("info", "--format", "{{.ServerVersion}}"),)]


def test_free_space_boundary():
    storage.require_free_space(20 * storage.GIB, "test drive")
    with pytest.raises(RuntimeError, match="Build refused"):
        storage.require_free_space(20 * storage.GIB - 1, "test drive")


def test_failed_build_never_starts_containers(monkeypatch):
    docker = Mock()
    monkeypatch.setattr(storage, "docker", docker)
    monkeypatch.setattr(storage, "host_preflight", Mock())
    monkeypatch.setattr(storage, "build", Mock(side_effect=subprocess.CalledProcessError(1, "docker")))
    monkeypatch.setattr(sys, "argv", ["docker_storage.py", "up"])
    assert storage.main() == 1
    assert all("up" not in call.args for call in docker.call_args_list)


def test_build_includes_dependencies_and_uses_dedicated_builder(monkeypatch):
    config = {"services": {
        "gateway": {"build": {}, "depends_on": {"domain": {}}},
        "domain": {"build": {}, "depends_on": {"kafka": {}}},
        "kafka": {"image": "kafka"},
    }}
    docker = Mock(return_value=Mock(stdout=json.dumps(config)))
    monkeypatch.setattr(storage, "docker", docker)
    monkeypatch.setattr(storage, "host_preflight", Mock())
    monkeypatch.setattr(storage, "ensure_builder", Mock())
    storage.build([], ["gateway"], Path("."))
    builds = [call.args for call in docker.call_args_list if "build" in call.args]
    assert {call[-1] for call in builds} == {"gateway", "domain"}
    assert all(call[-3:-1] == ("--builder", storage.BUILDER) for call in builds)
    assert storage.host_preflight.call_count == 2


def test_cache_cleanup_is_scoped_and_works_when_disk_is_full(monkeypatch):
    docker = Mock()
    monkeypatch.setattr(storage, "docker", docker)
    monkeypatch.setattr(storage, "host_preflight", Mock(side_effect=RuntimeError("full")))
    monkeypatch.setattr(sys, "argv", ["docker_storage.py", "prune-cache"])
    assert storage.main() == 0
    docker.assert_called_with("buildx", "prune", "--builder", storage.BUILDER, "--all", "--force")


def test_low_builder_space_blocks_build(monkeypatch):
    def docker(*args, **kwargs):
        if args[0:2] == ("buildx", "ls"):
            return Mock(stdout=storage.BUILDER + "\n")
        if args[0:2] == ("buildx", "inspect"):
            return Mock(stdout="Name: airport\nDriver: docker-container\n")
        return Mock(stdout="Filesystem 1024-blocks Used Available Capacity Mounted\n"
                           "/dev/sda 100000 99999 1 99% /var/lib/buildkit\n")

    monkeypatch.setattr(storage, "docker", docker)
    with pytest.raises(RuntimeError, match="builder filesystem"):
        storage.ensure_builder()
