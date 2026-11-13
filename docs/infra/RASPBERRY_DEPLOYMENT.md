# Raspberry deployment and validation

Deployment date: 2026-10-16. Public URL: <https://airportdt.duckdns.org>.
Host: `arthur@arthurrasp.local`. Deployment directory: `/opt/arthur-airport`.
The deployment contains the current local working tree; it has not been committed
or pushed by this task. The original development Compose profile is separate.

## Access and shared control

Visitors automatically receive a read-only viewer session. Operator ID `arthur`
has a randomly generated password stored on the Pi in the mode-0600 file
`/opt/arthur-airport/operator-credentials.txt`. Retrieve it privately over SSH:

```powershell
ssh arthur@arthurrasp.local cat /opt/arthur-airport/operator-credentials.txt
```

Sign in in the dashboard, then select **Acquire control**. One browser session
can control the shared airport at a time. A 120-second lease renews every 45
seconds while the controlling page remains active; release it before switching
devices. Sessions from the same account remain separate. A gateway restart
invalidates leases. Overlapping commands receive an explicit conflict; controls
and settings refresh when another session takes over. JWTs and lease secrets
remain in browser memory and expire; they are not saved in local storage.

All mutations require an operator role. Production also requires the lease and
an allowed route. Debug/Cypher, reset, training, LLM, external data-source changes,
planning and batch/scenario interfaces are denied at the gateway. Public reads
and operator settings have size/range limits. New routes are denied by default.

## Hosting and Raspberry profile

- Existing Traefik handles HTTPS and Let's Encrypt on `traefik-public`; only the
  dashboard joins that network. Domain and frontend networks are private.
- No airport service publishes a host port. Database, broker and gateway ports
  shown by `docker ps` without a host mapping are internal container ports.
- Existing ukom, medical-blogs and bapak containers were preserved and checked
  running. Existing host SSH and rpcbind listeners were observed; this task did
  not audit router exposure or alter unrelated host services.
- Approved boot change enabled memory cgroups and was followed by one reboot.
  Original boot command line: `/boot/firmware/cmdline.txt.before-airport`.
- Default demand: 50 flights/day, 1x speed; operators may select 10x, 50â€“100
  flights/day and passenger multiplier 0.1â€“1. Large simulation acceleration is
  unsuitable for this shared 4 GB host.
- Kafka runs as one KRaft broker with one partition per topic and 24-hour/16 MiB
  per-partition retention. Neo4j has a 640 MiB container budget, 256 MiB maximum
  heap and 64 MiB page cache. Python numerical libraries use one thread. Kafka uses a lightweight ApiVersions
  health probe; domain services allow three minutes for cold graph rebuilds.
- Containers have memory/CPU/PID limits and rotating logs. App services run
  without root, capabilities or writable root filesystems. Broker/database need
  writable persistent volumes. Read coalescing, a bounded two-second cache,
  upstream concurrency limits, rate limits and WebSocket limits bound public work.
- Passenger training is disabled. The analysis Pi image omits PyTorch/SB3 and
  uses the existing rule fallback. No LLM keys or real external data are used.
  These are explicit resource-profile differences from the full development stack.

## Monitoring and automatic protection

`airport-metrics.timer` records whole-host measurements once a minute, retaining
seven days in SQLite. `airport-guard.timer` checks RAM, disk, temperature and
airport volume growth once a minute. It freezes only the simulation container
if available RAM falls below 450 MiB, disk free below 5 GiB, temperature exceeds
80 C, or either graph/broker data volume exceeds 2 GiB. It does not delete data
or automatically resume. This protects headroom, but it is not an immediate
host-wide resource quota or an automatic cure for an exhausted disk.

The Windows dashboard script is
`C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py`:

```powershell
python C:\Users\arthu\Downloads\Programmation\raspberry_dashboard.py
```

Open <http://127.0.0.1:8765>. It fetches readings over SSH every 30 seconds,
shows indicator/danger zones, history, container resources and recommendations.
It binds only to loopback; no monitoring port was opened on the Pi. See
[PI_METRICS.md](PI_METRICS.md) for thresholds and exports.

## Validation evidence

| Check | Result |
|---|---|
| TypeScript production builds | Gateway and dashboard passed |
| Gateway auth, role, lease, policy, proxy and WebSocket tests | 23 passed |
| Dashboard store/event tests | 43 passed |
| Python monitoring, checkpoint and simulation-speed tests | 22 passed |
| Public HTTPS | 200, trusted TLS, HSTS, frame denial and CSP |
| Live anonymous/forged requests | 401 |
| Live viewer mutation and disabled administrative routes | 403 |
| Operator without lease / different session using lease | 423 |
| Second controller / overlapping operator commands | 409; one write succeeds |
| Excessive speed, flight count and query size | 400 |
| Eight simultaneous viewers | All 200 |
| Live WebSocket missing auth / foreign origin | Both rejected with 401 |
| Live WebSocket oversized frame | Closed with 1009 |
| Two live WebSocket viewers | Snapshots and identical simulation tick received |
| Orchestrator restart with paused clock | Exact time, tick, speed and pause state preserved |
| Production npm audits | Zero reported vulnerabilities in gateway and dashboard |

Live check scripts: `scripts/pi_verify.py`, `scripts/pi_websocket_check.cjs`,
`scripts/pi_control_check.py`, and `scripts/pi_latency.py`. Pi logs include
`live-security.log`, `latency.log`, and `python-audit-final.log`. Python installed
distributions are inventoried from all eight Python containers; the explicitly
approved audit queries PyPI with package names/versions only. Initial findings
were inherited pip 24.0 and setuptools 79.0.1. Dockerfiles now install
[pip 26.2.1](https://pypi.org/project/pip/26.2.1/) and
[setuptools 83.0.0](https://pypi.org/project/setuptools/83.0.0/).
The final scan checked 70 installed package versions with zero reported
advisories and zero failed/unknown lookups. Raw results are stored privately at
`/opt/arthur-airport/audit-results/python-pypi.json`.

Measured warm HTTPS reads were approximately 0.1â€“0.75 seconds; eight concurrent
reads completed within 0.6 seconds. The first cold concurrent flight read took
about 11–12.5 seconds during startup/backlog work. Baggage graph work can occupy the
database CPU budget, so these are measurements, not a latency guarantee.
The final warm check after maintenance measured 101–329 ms and eight concurrent
requests completed in 163–230 ms each. Final verification confirmed all 12
long-running airport containers running (all configured probes healthy), enforced
resource limits, zero published airport ports and matching source checksums.

The initial 1,219-sample overnight series covered private infrastructure/domain
services before the clock was enabled: 36â€“46.7 C and at least 1,347 MiB available
RAM. It is not a 24-hour full-simulation soak test. Full-clock operation and
bounded viewer/control tests were then measured separately. Building images can
increase host load and swap; the dashboard reports these warnings explicitly.

## Operations, backup and recovery

Run on the Pi, from `/opt/arthur-airport`:

```bash
docker compose --env-file .env.pi -f docker-compose.pi.yml ps
docker compose --env-file .env.pi -f docker-compose.pi.yml logs --tail 100 sim-orchestrator
systemctl status airport-metrics.timer airport-guard.timer
journalctl -u airport-guard.service --since today
```

After a guard freeze, inspect the cause and capacity before explicitly resuming:

```bash
docker compose --env-file .env.pi -f docker-compose.pi.yml unpause sim-orchestrator
```

Neo4j checkpoints clock/settings after ticks and commands. Kafka and graph state
live in named volumes. Checkpoint publication is not a distributed transactional
outbox; an abrupt crash can replay the last interval. Domain restart/replay and
full multi-day capacity have not been exhaustively tested.

Create a consistent private cold backup (brief airport-only interruption):

```bash
sudo python3 /opt/arthur-airport/scripts/pi_backup.py
sudo ls -lh /var/backups/arthur-airport
```

The archive contains stopped graph/broker volumes, deployment sources, image IDs,
an online SQLite backup, and credentials. It stays in a root-only directory;
never serve or publish it. The script restarts the airport in a `finally` block
and verifies archive members before naming the final `.tar` file. Move a copy
to separate private storage for protection against SD-card failure.

Created and verified: `/var/backups/arthur-airport/20261016T141119Z.tar`
(563 MiB, mode 0600). Startup waits for graph/broker health and can take several
minutes on this Pi. That archive precedes the final dashboard reconnect-display
correction; its simulation data and credentials remain a consistent recovery point.

For recovery, stop this Compose project, take another backup of its current
state, and restore the selected archive's `deployment/` into the deployment
directory and each `volumes/` subtree into the matching inspected Docker volume
mountpoint, preserving ownership. Restore the metrics SQLite file with its timer
stopped. Use the manifest's retained images or rebuild from restored sources,
then start this project with `up -d --no-build` and rerun the live checks. Do not
run `down -v`. A destructive full-volume restore was not exercised on this host.

Security checks cover the deployed application access boundaries and Python/npm
advisory inventories. They do not prove the absence of vulnerabilities or replace
an independent penetration test. OS/JVM/container-engine vulnerability scanning,
internet-scale denial-of-service protection and multi-replica operation are
outside this validation. A single gateway holds the controller lease; deploying
multiple gateway replicas requires shared lease state first.
