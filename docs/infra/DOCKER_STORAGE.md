# Keeping Docker storage under control

Use Python 3.11+, Docker Desktop/Engine, Compose with `build --builder`, and
Buildx 0.14+ (`default-load` support). The tool is for a **local** Docker context.
It does not manage remote builders or the Pi deployment.

## Daily commands

From the repository root, with Docker running:

```powershell
python scripts/docker_storage.py status
python scripts/docker_storage.py up
# Rebuild/start just the service you changed:
python scripts/docker_storage.py up analysis-service
# Include the optional monitoring stack:
python scripts/docker_storage.py up --profile observability
# Stop without removing persistent data:
docker compose down
```

`up` builds services one at a time with the dedicated
`arthur-airport-storage-v1` builder, then runs Compose with `--no-build`.
The first build creates that builder with `infra/docker/buildkitd.toml`; it
does not change your globally selected builder or Docker daemon settings.
Its cache starts empty, so the first build downloads dependencies again.
Use `build` instead of `up` to build without starting containers.

Before building, and between services, the guard refuses to continue below
20 GiB free on both Docker's host drive and the builder filesystem. A single
build can still consume more than the remaining space: this is a preflight,
not a continuous monitor or filesystem quota. The guard fails on Docker errors.
By default Windows checks `%LOCALAPPDATA%\Docker\wsl`'s drive, even if the repo
is on another drive. If you moved Docker's disk, pass a path on its actual drive:

```powershell
python scripts/docker_storage.py up --disk-path D:\Docker
```

On Linux the default is `/var/lib/docker`; override for rootless/custom storage.
Plain `docker compose up --build`, IDE rebuild buttons, and other builders bypass
the cache and free-space safeguards. Container logging/retention settings still
apply when using the main Compose file.

## Budgets and tradeoffs

| Storage | Default policy | Limits of the policy |
| --- | --- | --- |
| Dedicated BuildKit cache | GC above 12 GB, keep at least 2 GB; target 20 GB free; stale download/context caches targeted above 2 GB after 24h | Soft GC targets; active builds can exceed them. Does not cover the old default builder or exported images. |
| Build concurrency | One service and one BuildKit step at a time | Slower full builds, lower peak disk usage. |
| Container stdout/stderr | JSON log rotation: 10 MB × 3 files per container | Applies after containers are recreated, including optional profiles. |
| Kafka | 7 wall-clock days or 64 MiB **per partition**, 16 MiB segments, hourly roll, minute cleanup checks | Shorter replay under load. Active segments, deletion delay, internal topics and explicit topic overrides add space. Current 53 application partitions target about 3.3 GiB before overhead. |
| Neo4j transaction logs | 256 MiB retention, 16 MiB rotation | Active/checkpoint logs and entity database are additional; no entity deletion. |
| ZooKeeper | Autopurge hourly, retain 3 snapshots | Active logs and snapshots remain. |
| Prometheus | 1 GB or 7 days | WAL/head blocks and temporary compaction space are additional. |
| Loki | 7 days with retention compactor | Time retention, no byte quota; deletion delayed by 2h and compaction. Existing ingested logs may retain their earlier policy. |

Kafka's byte policy intentionally makes seven days an upper bound, rather than
a guaranteed replay window. This operational policy is documented in DOCKER.md;
it does not change event schemas or simulation-clock behavior. Topics with
explicit retention overrides must be reviewed separately using `kafka-configs`.

The analysis image retains full CPU PPO support. The torch install precedes
`COPY requirements.txt`, so editing other dependencies reuses the large torch
layer. The official CPU index prevents selecting CUDA wheels for that install.
Pip/npm caches stay in BuildKit cache mounts, where the dedicated builder's GC
can reclaim them. Generated model archives, checkpoints, caches and test output
are excluded from service build contexts. Model files belong in the existing
`analysis-artifacts` and `passenger-ml` volumes, rather than being baked into images.

## Cleanup and Windows disk reclamation

To explicitly discard only this project's **builder cache**:

```powershell
python scripts/docker_storage.py prune-cache
```

This preserves images, containers, Neo4j/Kafka volumes and training artifacts.
There is no automatic volume deletion, global image pruning, factory reset,
or VHDX compaction in the tool. The previous default builder's accumulated cache
is separate: inspect it with `docker system df` / `docker buildx ls` and choose
cleanup separately. The new policy does not retroactively clean 279 GB of old data.

For builds that bypass the wrapper, Docker Desktop's Settings → Docker Engine
can additionally enable default-builder GC. **Merge** this into the existing
JSON, preserving other settings, then Apply & restart:

```json
{
  "builder": {
    "gc": {"enabled": true, "defaultKeepStorage": "12GB"}
  }
}
```

This is a machine-wide default-builder cache policy, not a cap on all Docker data.
The repository deliberately does not overwrite Docker Desktop's settings file.

Docker's VHDX can remain large after internal cleanup. Shut down Docker/WSL and
use the supported Windows/WSL disk-compaction procedure for your installation
after backing up durable data. Docker Desktop's **Clean / Purge data deletes
volumes** and is not a volume-preserving compaction method.

There is no portable Compose quota on a WSL2 VHDX or local named volume.
Neo4j entities, retained audit history, runtime images and model archives can
still grow. Check `status` regularly; a hard total budget requires host-level
storage capacity/quota management. These changes reduce growth and catch low
space before builds; they cannot promise the entire host disk never fills.

References: [BuildKit GC](https://docs.docker.com/build/cache/garbage-collection/),
[BuildKit configuration](https://docs.docker.com/build/buildkit/toml-configuration/),
[Compose build](https://docs.docker.com/reference/cli/docker/compose/build/),
[Neo4j transaction logs](https://neo4j.com/docs/operations-manual/current/database-internals/transaction-logs/),
[Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/).
