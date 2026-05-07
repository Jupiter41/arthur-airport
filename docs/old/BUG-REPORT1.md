# 🐛 Bug Report — CI Failures & System Inconsistencies

## 📚 Context

Read these files in order:

- BUG-REPORT.md — this file, describing current issues
- CLAUDE.md — architecture rules and constraints
- docs/skills/SKILL.md — cross-cutting patterns
- TODO.md — tasks + desired output
- docs/lessons-learned/\*.md — all accumulated lessons
- All SPEC.md and SKILL.md files across services

Focus especially on:

- System-wide consistency
- Failure recovery behavior
- Test coverage of critical logic
- Developer experience (DX)
- Clean reproducibility

---

## 🎯 GOAL

Fix CI pipeline failures, ensure code quality compliance, and investigate system-level inconsistencies affecting airport flow simulation (passengers, baggage, and infrastructure linkage).

---

## ❌ Issue 1 — CI Pipeline Fails (Ruff Lint Errors)

The GitHub CI pipeline fails due to multiple linting issues detected by `ruff`.

### Summary

- **15 total errors**
- **13 auto-fixable (`--fix`)**
- **2 require manual intervention**

### 🔍 Errors Breakdown

#### Unused Imports (F401)

File: `services/flight-service/kafka/consumer.py`

- `services.state_machine.TERMINAL_STATES`
- `services.gate_resolver.check_and_resolve_conflict`
- `metrics.runway_queue_depth`
- `metrics.gate_conflicts_resolved_total`
- `metrics.turnaround_delay_minutes`

File: `services/flight-service/models/domain.py`

- `datetime.datetime`

File: `services/flight-service/routers/flights.py`

- `datetime.datetime`
- `FlightListResponse`
- `FlightSummary`
- `FlightDetail`
- `RunwayInfo`
- `GateInfo`
- `CascadeResponse`

#### Unused Variables (F841)

File: `services/flight-service/kafka/consumer.py`

- `updated` (assigned but never used)
- `severity` (assigned but never used)

### ✅ Expected Fix

- Remove all unused imports
- Remove or properly use unused variables
- Ensure `ruff check --fix` passes cleanly
- CI pipeline should succeed after fixes

---

## ⚠️ Issue 2 — Passenger Flow Imbalance

### Problem

- All passengers are assigned to **Terminal B**
- Results in:
  - Extremely high **security wait times**
  - Severe congestion at **baggage induction B**
  - Cascading system issues (delays, bottlenecks)

### ❓ Questions

- Is terminal assignment logic working correctly?
- Is load balancing across terminals implemented or broken?
- Are upstream services (flight assignment, routing) misconfigured?

### ✅ Expected Behavior

- Passengers should be distributed across terminals (A, B, C)
- Load should be balanced based on capacity or rules
- No single terminal should become a bottleneck by default

---

## ⚠️ Issue 3 — Baggage System Topology Inconsistencies

### Problem 1 — Missing Links

- Baggage belts are **not linked to Make-Up areas**

### Problem 2 — Partial Induction Mapping

Observed:

- Screen 1 → Induction A ✅
- Screen 3 → Induction B ✅
- Screen 5 → Induction C ✅

But:

- Screen 2 → ❌ no induction
- Screen 4 → ❌ no induction
- Screen 6 → ❌ no induction

### ❓ Questions

- Is this intentional or a data/config issue?
- Are mappings incomplete or dynamically assigned?
- Is there a failure in graph relationships (Neo4j?) or ingestion logic?

### ✅ Expected Behavior

- Every screen should be connected to a valid induction
- Belts should be linked to Make-Up zones
- Graph topology should be complete and consistent

---

## ⚠️ Issue 4 — Arrival Carousels Always Zero

### Problem

- Arrival carousel values are always `0`

### Hypothesis

- Likely caused by upstream issues:
  - Broken baggage flow
  - Missing belt → Make-Up connections
  - Incorrect routing or aggregation

### ❓ Questions

- Is data not flowing into arrival computation?
- Are events not triggering updates?
- Is this a symptom of Issue 3?

### ✅ Expected Behavior

- Arrival carousels should reflect actual baggage flow
- Values should dynamically update based on system state

---

## 🔗 Cross-Cutting Concerns

Please investigate with a **system-wide perspective**:

- Are Kafka events properly consumed and propagated?
- Are Neo4j relationships correctly created and updated?
- Are domain models aligned with actual data usage?
- Are there silent failures or ignored states?
- Is observability (metrics/logs) sufficient to debug this?

---

## 🧪 Testing & Validation

- Add/verify tests for:
  - Terminal assignment logic
  - Baggage routing graph integrity
  - Event-driven updates (Kafka → state changes)

- Ensure reproducibility:
  - Local environment matches CI
  - Deterministic behavior where possible

---

## ✅ Definition of Done

- CI pipeline passes with zero lint errors
- Passenger load is balanced across terminals
- Baggage system graph is fully connected and consistent
- Arrival carousels reflect real values (not always 0)
- No unused code or dead variables remain
- System behavior is test-covered and reproducible

---

## 💡 Notes

Focus not only on fixing symptoms but identifying **root causes**, especially where multiple issues may be linked (e.g., baggage topology → arrival metrics).

---
