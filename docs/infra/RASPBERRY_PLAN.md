# Raspberry deployment plan

Date: 2026-10-15. Public hostname: `airportdt.duckdns.org`.

Execution and validation: 2026-10-16. See
[RASPBERRY_DEPLOYMENT.md](RASPBERRY_DEPLOYMENT.md) for the deployed profile,
test evidence, operating instructions, measured limits and recovery procedure.

## Intended behavior

One shared airport. Public visitors can observe it. Only authenticated operators
can change it, and only the operator holding an exclusive, expiring controller
lease can issue commands. Administrative debug, database, training, reset, and
unbounded batch interfaces must not be exposed on the public deployment.

This updates the development JWT-stub deployment described in OVERVIEW.md and
the gateway SPEC.md. Kafka communication, simulation time, and Neo4j authority
remain the project contracts. Controller leases are transient gateway security
state, not airport domain state; restart invalidates them.

## Execution order

1. Pull the latest repository; inspect existing changes without overwriting them.
2. Inventory the Pi over SSH: architecture, memory, disk, Docker, running sites,
   Traefik networks/entrypoints/resolver, DNS, exposed ports, and backup options.
   Read the hosting example in the local directory `ziaprofesi`.
3. Specify the production access contract before implementation. Enforce viewer
   versus operator permissions centrally, validate credentials and JWT claims,
   limit login attempts, and remove development credentials from production UI.
4. Add exclusive controller sessions and serialized bounded writes. Reject other
   controllers, expired leases, and overlapping writes explicitly. Show access
   status and operator login/control acquisition in the dashboard.
5. Prepare a separate ARM64 production Compose stack using the existing Traefik
   HTTPS edge. Publish no database, broker, gateway, or domain service host ports.
   Use private networks, secrets outside Git, bounded logs, resources, and
   persistent volumes. Do not alter other websites or the shared proxy.
6. Fit the workload to measured spare Pi capacity: one broker, small graph cache,
   limited numerical threads, bounded WebSocket connections/buffers/messages,
   reduced initial simulation load/speed, no on-device training or external live
   data. Keep optional large models out of the Pi image with documented fallback.
7. Test access control, malformed/forged credentials, endpoint bypasses,
   concurrent operators, lease expiry, write conflicts, login throttling,
   WebSocket authentication/origin/limits, dependency vulnerabilities, and builds.
8. Back up existing airport state if present. Build sequentially, deploy only
   airport containers, verify health/readiness, TLS, DNS, WebSocket delivery,
   private ports, and resource use alongside existing websites.
9. Run bounded security/concurrency/load checks against the deployed airport,
   inspect errors and resource pressure, and tune within safe limits. Record
   evidence, remaining risks, operations commands, backup/rollback, and status.

## Acceptance criteria

- HTTPS works at the public hostname and only the dashboard joins Traefik.
- Anonymous visitors cannot mutate any domain state; operator commands require
  a current exclusive lease. Public debug/training/reset access is denied.
- Multiple viewers receive updates; two operators cannot silently overwrite one
  another through concurrent browser commands.
- Domain services, Neo4j, and Kafka have no published host ports.
- The Pi retains capacity for its existing sites; memory/log/event growth is
  bounded and sustained operation is measured, not assumed.
- Validation results distinguish local tests from live Pi verification.

## Initial observations

- Repository pull: already up to date.
- Existing example: shared Traefik, `traefik-public`, entrypoints `web` and
  `websecure`, ACME resolver `letsencrypt`; verify these on the Pi.
- First sandbox SSH attempt could not resolve mDNS. Retry using normal host
  network permissions before treating this as a Raspberry configuration issue.
- Existing gateway has roles and production credentials, but most mutation
  routes are not role gated and the dashboard requests a development credential.
