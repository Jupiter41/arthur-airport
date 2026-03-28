# Sprint 12 - Scenarios Page Lifecycle (Create, Edit, Delete, Fork)

Date: 2026-03-28

## Objective
Implement full scenario lifecycle support from the Scenarios page:
- Create custom scenarios
- Edit custom scenarios
- Delete custom scenarios
- Fork scenarios
- Keep base scenarios immutable

## What Changed

### Backend - sim-orchestrator

1. Scenario engine metadata and storage split
- Added support for two scenario roots:
  - base definitions directory
  - user definitions directory
- Added per-scenario metadata in memory:
  - is_base
  - file_path

2. Scenario definition lifecycle methods
- Added create_definition
- Added update_definition
- Added delete_definition
- Added fork_definition

3. Immutability and safety rules
- Base scenarios cannot be updated or deleted
- Running scenario cannot be updated or deleted while active
- Duplicate name conflicts are rejected

4. API payload enrichment
- list_scenarios now includes is_base
- get_definition_payload returns full definition plus is_base

5. New/updated scenario API endpoints
- POST /api/v1/scenarios
- PUT /api/v1/scenarios/{name}
- DELETE /api/v1/scenarios/{name}
- POST /api/v1/scenarios/{name}/fork
- GET /api/v1/scenarios/{name} updated to include metadata payload

### Frontend - art-dashboard

1. API client additions
- Added scenarios create, update, delete, and fork methods in useApi

2. Scenarios page UX enhancements
- Added New action to create custom scenarios
- Added editor mode flows:
  - create
  - edit
  - fork
- Added save/cancel flow with JSON validation
- Added custom-only delete with confirmation
- Added BASE/CUSTOM visual badges
- Disabled edit/delete affordances for base scenarios
- Preserved run/stop/results behavior and query invalidation after writes

### Documentation
- Updated sim-orchestrator README with Scenario API section and endpoint table

## Bugs/Issues Addressed Along The Way

1. Environment mismatch during test run
- Initial Python test run used a non-project interpreter and failed due to missing dependencies
- Fixed by running tests with the project venv interpreter from repository root

2. Working directory mismatch during test invocation
- Fixed by explicitly running pytest from repository root path

## Validation and Test Results

1. Frontend build
- Command: npm run build (dashboard)
- Result: success
- Note: bundle size warning present, no build failure

2. Targeted backend unit tests
- Command: python -m pytest tests/unit/test_sim_scenario_engine_crud.py -q
- Result: 4 passed

3. Diagnostics
- Changed backend/frontend files checked for editor diagnostics
- Result: no errors reported in changed files

## Outcome
The Scenarios page now supports full custom scenario lifecycle management while protecting base scenarios from mutation. Backend API, persistence logic, UI actions, and tests are aligned with the requested behavior.

## Follow-up Ideas
- Replace raw JSON editor with a structured form for safer authoring
- Add API-level smoke script for create/edit/delete/fork against a running stack
