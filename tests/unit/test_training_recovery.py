"""G7: durable training runs resume after interruption and stale owners are fenced."""

import asyncio
import io
import json
import zipfile

import pytest

from tests.conftest import import_service_module


class FakeStore:
    """In-memory stand-in with the same lease semantics as services.training_store."""

    def __init__(self, store_module):
        self.claimable = store_module.claimable
        self.runs: dict[str, dict] = {}
        self.leases: dict[str, tuple[str | None, int]] = {}
        self.now = 1_000
        self.order: list[str] = []

    async def create(self, document):
        if any(d["status"] == "running" and self.leases[i][1] > self.now for i, d in self.runs.items()):
            raise ValueError("Training run already in progress")
        self.runs[document["id"]] = dict(document)
        self.leases[document["id"]] = (None, 0)
        self.order.append(document["id"])
        return document

    async def claim(self, token, ttl, run_id=None):
        for rid in self.order:
            if run_id and rid != run_id:
                continue
            document = self.runs[rid]
            if not self.claimable(document["status"], self.leases[rid][1], self.now):
                continue
            document.update(status="running", attempt_count=document.get("attempt_count", 0) + 1)
            self.leases[rid] = (token, self.now + int(ttl * 1000))
            return dict(document)
        return None

    def _owned(self, rid, token):
        owner, until = self.leases.get(rid, (None, 0))
        return owner == token and until > self.now and self.runs[rid]["status"] == "running"

    async def save(self, document, token, ttl):
        if not self._owned(document["id"], token):
            return False
        self.runs[document["id"]] = dict(document)
        self.leases[document["id"]] = (token, self.now + int(ttl * 1000))
        return True

    async def renew(self, rid, token, ttl):
        return self._owned(rid, token)

    async def finish(self, document, token):
        if not self._owned(document["id"], token):
            return False
        self.runs[document["id"]] = dict(document)
        self.leases[document["id"]] = (None, 0)
        return True

    async def release(self, document, token):
        if not self._owned(document["id"], token):
            return False
        self.runs[document["id"]] = dict(document, status="queued")
        self.leases[document["id"]] = (None, 0)
        return True

    async def list_recent(self, limit=20):
        return [self.runs[i] for i in reversed(self.order)][:limit]


class Process:
    """Subprocess double: runs until ``finish`` is called, then exits."""

    def __init__(self, cmd, artifact_on_exit=True):
        self.cmd = cmd
        self.returncode = None
        self.stdout = io.BytesIO(b"")
        self.terminated = False
        self.artifact_on_exit = artifact_on_exit

    def poll(self):
        return self.returncode

    def finish(self, code=0):
        if code == 0 and self.artifact_on_exit:
            output = self.cmd[self.cmd.index("--output") + 1]
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("synthetic-test-policy", "test")
        self.returncode = code

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def training(tmp_path, monkeypatch):
    module = import_service_module("analysis", "services.training_manager")
    store_module = import_service_module("analysis", "services.training_store")
    monkeypatch.setenv("TRAINING_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("RL_MODEL_PATH", str(tmp_path / "rl_policy.zip"))
    monkeypatch.setenv("TRAINING_LEASE_SECONDS", "3")
    processes = []

    def popen(cmd, **_):
        process = Process(cmd)
        processes.append(process)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    return module, FakeStore(store_module), processes


async def _until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.05)


def test_claim_rule():
    store = import_service_module("analysis", "services.training_store")
    assert store.claimable("queued", 0, 10)
    assert store.claimable("running", 9, 10)          # abandoned: lease expired
    assert not store.claimable("running", 11, 10)     # live owner
    for terminal in ("completed", "failed", "stopped"):
        assert not store.claimable(terminal, 0, 10)


def test_abrupt_exit_is_resumed_from_checkpoint_with_same_seed(training):
    module, store, processes = training

    async def scenario():
        first = module.TrainingManager(store)
        run = await first.start_training("rl", 10_000)
        assert run.attempt_count == 1 and run.seed is not None
        cmd = processes[0].cmd
        assert "--resume" not in cmd and cmd[cmd.index("--seed") + 1] == str(run.seed)
        # The trainer checkpointed 4000 steps and reported 4500 before the host died.
        directory = module.Path(run.checkpoint_dir)
        with zipfile.ZipFile(directory / "latest.zip", "w") as archive:
            archive.writestr("checkpoint", "4000")
        (directory / "checkpoint.json").write_text(json.dumps({"timesteps": 4000}))
        (directory / "progress.json").write_text(json.dumps({"timesteps": 4500}))
        await _until(lambda: store.runs[run.id].get("current_timesteps") == 4500)
        assert store.runs[run.id]["progress_estimated"] is False
        first._monitor_task.cancel()          # abrupt exit: no release, no finish
        store.now += 10_000                   # lease expires

        second = module.TrainingManager(store)
        resumed = await second.recover()
        assert resumed is not None and resumed.id == run.id
        assert resumed.attempt_count == 2 and resumed.seed == run.seed
        assert resumed.resumed_from_timesteps == 4000
        cmd = processes[1].cmd
        assert cmd[cmd.index("--resume") + 1] == str(directory / "latest.zip")
        assert cmd[cmd.index("--seed") + 1] == str(run.seed)
        processes[1].finish(0)
        await _until(lambda: store.runs[run.id]["status"] == "completed")
        assert module.Path(module.os.environ["RL_MODEL_PATH"]).is_file()
        assert store.leases[run.id] == (None, 0)

    asyncio.run(scenario())


def test_live_lease_blocks_second_claim_and_stale_owner_is_fenced(training):
    module, store, processes = training

    async def scenario():
        owner = module.TrainingManager(store)
        run = await owner.start_training("rl", 2_000)
        competitor = module.TrainingManager(store)
        assert await competitor.recover() is None
        with pytest.raises(ValueError):
            await competitor.start_training("rl", 2_000)
        # Owner stalls past its lease; a replica takes the run over.
        owner._monitor_task.cancel()
        try:
            await owner._monitor_task
        except asyncio.CancelledError:
            pass
        store.now += 10_000
        replacement = await competitor.recover()
        assert replacement.attempt_count == 2
        # The stale owner can neither publish progress nor complete the run.
        assert await owner._persist(run) is False
        run.status = "completed"
        assert await owner._finish(run) is False
        assert store.runs[run.id]["status"] == "running"
        processes[1].finish(0)
        await _until(lambda: store.runs[run.id]["status"] == "completed")

    asyncio.run(scenario())


def test_lost_lease_terminates_attempt_without_promotion(training):
    module, store, processes = training

    async def scenario():
        manager = module.TrainingManager(store)
        run = await manager.start_training("rl", 2_000)
        store.leases[run.id] = ("someone-else", store.now + 60_000)
        await _until(lambda: processes[0].terminated)
        await _until(lambda: manager.active_run is None)
        assert not module.Path(module.os.environ["RL_MODEL_PATH"]).exists()
        assert store.runs[run.id]["status"] == "running"   # still owned by the replacement

    asyncio.run(scenario())


def test_graceful_shutdown_releases_and_operator_stop_is_terminal(training):
    module, store, processes = training

    async def scenario():
        manager = module.TrainingManager(store)
        run = await manager.start_training("rl", 2_000)
        await manager.shutdown()
        assert processes[0].terminated
        assert store.runs[run.id]["status"] == "queued"
        resumed = await module.TrainingManager(store).recover()
        assert resumed.id == run.id and resumed.attempt_count == 2
        stopper = module.TrainingManager(store)
        stopper.active_run, stopper._process, stopper._token = resumed, processes[1], store.leases[run.id][0]
        assert await stopper.stop_training() is True
        assert store.runs[run.id]["status"] == "stopped"
        assert await module.TrainingManager(store).recover() is None

    asyncio.run(scenario())


def test_failed_attempt_is_persisted_and_not_retried(training):
    module, store, processes = training

    async def scenario():
        manager = module.TrainingManager(store)
        run = await manager.start_training("rl", 2_000)
        processes[0].finish(3)
        await _until(lambda: store.runs[run.id]["status"] == "failed")
        assert await module.TrainingManager(store).recover() is None
        status = await manager.get_status()
        assert status["history"][-1]["status"] == "failed"
        assert status["history"][-1]["attempt_count"] == 1

    asyncio.run(scenario())
