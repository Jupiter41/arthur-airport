# UI implementation validation

Date: 2026-11-15. The implementation contract is [UI_IMPLEMENTATION.md](UI_IMPLEMENTATION.md); the tracked backlog is [UI_TODO.md](../../UI_TODO.md).

## Delivered

- Operations, Planning and System workspaces, persistent labelled navigation, responsive drawer, domain SVG icons, compact simulation status and account dialog.
- Native dialog focus containment/Escape, explicit focus return, keyboard flight inspection/sorting, skip navigation, reduced-motion styling and dark/light semantic surfaces/status badges.
- Exception-led Overview, current runway/terminal context, next-hour schedule context and pending approvals. Completed movements are excluded from active-flight counts; UTC formatting and time sorting normalize offsets.
- Full-width/split flight boards, URL filters/sort/selection/pagination, optional type column and density, stable live-update ordering, live store-derived details and direct-ID recovery.
- Board/Map/3D modes with legacy-link compatibility, retained scope/selection, schematic layers, textual entity selection, shared domain records/actions, terminal comparisons, actual baggage scans, and no invented healthy heatmap cells.
- Incident detail links and contextual decision history; server-side decision search and terminal filters before pagination; approval/dispatch/execution/measurement distinctions remain intact.
- Baseline/configuration/results/investment/audit experiment views, retained scenario IDs, preserved builder drafts across local tabs, shared-airport versus isolated effects, disabled unauthorized experiment controls, and explicit unavailable states.
- Shared-airport simulation panel, focused reset confirmation, partial-data-labelled snapshot export, incident lab separation, Help/teaching page, responsive supporting layouts and map height correction.

## Automated checks

Final checks passed: TypeScript compilation and Vite production build; 92 dashboard tests across 18 Vitest files; 7 Python decision-history tests. Decision-history tests cover filtering before pagination, search normalization, invalid filter bounds and existing lifecycle evidence. Vite still reports the existing large optional map/chart/3D chunk warning and an outdated Browserslist database; test tooling reports its esbuild/oxc configuration deprecation warning.

Regression coverage specifically exercises stable flight ordering despite update highlights, UTC-offset ordering, retained flight/terminal URL state, Board default and legacy 3D links, operational tools remaining available in spatial views, terminal navigation in 3D, absent heatmap zones, workspace separation, decision playback and what-if request schemas.

## Browser observations

The local Vite preview was checked against the available synthetic operational backend. Read-only inspection used existing data; no incident injection, approval, reset or new planning run was performed.

- Dark and light Overview and flight-board screenshots were inspected.
- 1440×900 and 1280×720 desktop layouts, 768×1024 tablet navigation and 390×844 phone flight monitoring/inspection were exercised. Checked views had no document-level horizontal overflow; dense tables scroll inside their containers.
- Selecting a terminal and switching Board → Map retained scope and left records/actions accessible. Keyboard-accessible entity selection remains available alongside the schematic.
- Native account dialog opened, closed with Escape and returned focus to the sign-in trigger. Tablet navigation uses a compact left drawer. Incident details use bounded query reconciliation rather than repeated fetches when cascade evidence is absent; direct baggage records remain accessible during conveyor-view failure.
- Operational route shells and planning entry points rendered. Some supporting-route checks captured loading states only; they do not certify all-route completion or responsive coverage.
- Planning baseline/library requests were unavailable in the running backend. The UI labels that failure and does not substitute an empty library or invented baseline. New decision search/filter behavior was verified in Python tests, not in a rebuilt running analysis container.

## Remaining validation and limits

- Human formative usability sessions and the proposed time-to-find/completion targets have not been run.
- Full WCAG 2.2 AA verification, assistive-technology testing, all-route breakpoint checks and actual 200% browser zoom remain outstanding. Larger controls, readable typography and shared focus semantics are implemented; they are not a certification claim.
- The original rendered baseline was unavailable during the initial review. Current screenshots are evidence of the delivered state only.
- Some domain observations omit per-record timestamps or entity impact. Source clock, fetch age and known incident start times remain distinct; absent evidence is not manufactured.
- Search explicitly labels bounded flight/incident observations and exact baggage-tag lookup. It is not an exhaustive passenger/graph search.
- Applying server-side search to a deployed stack requires rebuilding/redeploying analysis-service using the repository storage guard. Deployment was not part of this source-change/push request.
