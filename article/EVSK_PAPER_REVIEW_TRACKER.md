# EVSK Paper: Reviewer Comment Tracker

Working document for the camera-ready revision of _A Layered Architecture for Digital Twins with Progressive Fidelity: A Case Study in Airport Operations with Specification-First Development_ (Chevallier and Castignani, LIST).

**Status as of 2026-09-29.** All review items are resolved in the active manuscript. Where a code finding was handled by narrowing a paper claim rather than changing the implementation, the completion note says so explicitly.

## How to read this file

- **Reviewer requests** are the items requested by the reviewers, grouped as in their report (mb12 is the reviewer who asked about the human-intervention perimeter and the L2 to L3 boundary).
- **Findings from code verification** are problems found while checking the paper's claims against the public repository. They matter because the repository is linked in the paper and can be inspected by reviewers.
- **Consistency fixes** are inconsistencies inside the manuscript that were not raised by reviewers but should be fixed before submission.

## 1. Reviewer requests

| #   | Request                                                          | Where                   | Status   | Completion note |
| --- | ---------------------------------------------------------------- | ----------------------- | -------- | --------------- |
| 1   | Strip LLM/agent claims from abstract and contributions           | Title, abstract, intro  | **Done** | Abstract and contributions now state architectural and empirical claims only (`article_corrected.tex`; `sections/introduction.tex`). |
| 2   | Demote agents, define the human-intervention perimeter (mb12)    | Section 4               | **Done** | Coding assistance is operational context; the human specification, contract, review, and correction perimeter is explicit in Section 4. |
| 3   | Align RQ2 wording                                                | Intro, Section 7        | **Done** | RQ2 is identical in the Introduction and Discussion, and Related Work now motivates independent verification. |
| 4   | Position the concrete AI/ML models under L3                      | Section 5               | **Done** | Section 5 now makes the architectural exception explicit: the queue forecaster is an embedded L0 feedback component because its output changes L0 queue draining; only scenario analysis, anomaly detection, optimisation, appraisal, and gated recommendations are claimed as L3 evidence. Prototype planning-predictor scores remain excluded. |
| 5   | Formal fidelity definition (spatial, temporal, behavioural)      | Section 3               | **Done** | Definition and Table 1 consistently map all three dimensions across L0--L3. |
| 6   | Why progressive fidelity matters                                 | Intro, Section 3        | **Done** | Introduction and Section 3 explain incremental data/model availability and restructuring risk. |
| 7   | Frame as an architectural invariant                              | Sections 3, 4, 5        | **Done** | The append-only fidelity-preservation invariant and contract dependencies are stated and shown in Figure 1. |
| 8   | Remove commit hashes and file counts                             | Section 6               | **Done** | All hashes, repository file counts, and directory-density arguments were removed. |
| 9   | Reframe around blast radius and modularity                       | Section 6               | **Done** | Section 6 now uses a path-level repository analysis and a blast-radius table for four upgrades. |
| 10  | Show layer isolation empirically                                 | Section 6               | **Done** | Table 2 reports touched subsystems, contract/consumer effects, and lower-layer edits. The BTS path is retained as a negative result: contracts stayed compatible but L0 generators imported calibration logic. |
| 11  | L2 to L3 data integrity (mb12)                                   | Section 3               | **Done** | Section 3 lists implemented parsing, filtering, Pydantic, envelope, and idempotency checks; discloses missing runtime schema/provenance validation and the planning-adapter bypass; and documents the present approval gate, RBAC, supported command mappings, in-memory queue, and future hardening. |
| 12  | Contrast with ISO 23247, Tao 5D, 3-tier IoT, with a failure mode | Related Work            | **Done** | Related Work contrasts all three and gives message-change and data--service-coupling failure modes; `tao2018` was verified and cited. |
| 13  | Update the Related Work gap statement                            | Related Work            | **Done** | The gap is now backward-compatible fidelity evolution; the AI-assisted SE paragraph is reduced to RQ2 context. |
| 14  | UML component/interface diagrams                                 | Figure 1, annex figures | **Done** | Figure 1 uses UML-style components and provided-interface symbols. Overlapping L3 blocks were separated and the dashed command path was routed around the component stack. The text states that this is an architectural view, not executable UML, and makes no agent-performance claim. |
| 15  | Generalizability paragraph                                       | Section 3               | **Done** | Section 3 maps the layer order to hospitals, ports, manufacturing, and mobility; Section 7 limits the evidence to one case. |
| 16  | Camera-ready admin                                               | Front matter            | **Done** | Funding/acknowledgment text is neutral, the GitHub repository is the sole reproducibility link in the paper, bibliography metadata was corrected, and references start on a new page before the Annex. |

## 2. Findings from code verification

| Item                                                                         | Where                     | Status   | Completion note |
| ---------------------------------------------------------------------------- | ------------------------- | -------- | --------------- |
| Fix demand regressor (target duplicated in a feature, constants at training) | Paper resolution          | **Done** | Code deliberately unchanged; Section 5 labels it a prototype and reports no MAE/RMSE evidence. |
| Fix delay classifier (labels are a threshold rule)                           | Paper resolution          | **Done** | Code deliberately unchanged; Section 5 labels it a prototype and reports no AUC evidence. |
| Route `training_pipeline` through the BTS adapter                            | Paper resolution          | **Done** | Code deliberately unchanged; Section 3 discloses the bypass and excludes the predictors from the evaluation. |
| Scope the shared-registry claim to three services                            | Section 5, Annex Fig. 3   | **Done** | Claim now names the simulation orchestrator, weather service, and passenger service and identifies planning's local factory. |
| `ROUTES.md` missing the planning passthrough                                 | Repo docs                 | **Done** | Added `/api/v1/planning/*` to the gateway passthrough table in `docs/architecture/ROUTES.md`. |

### Details of the verification

- The delay classifier and demand regressor bypass the adapter interface: `training_pipeline.py` reads the BTS CSV directly, while the scenario engine reads it through `BTSAdapter`.
- The delay classifier's labels come from a load-factor and seasonality threshold rule, four of its eight features are constants, and one feature is computed from the label. Its reported discrimination measures label construction, not predictive skill.
- The demand regressor's target is duplicated into one of its features, and several features are constant at training but vary at inference. Its reported error is optimistic.
- The shared data-source registry has three importers (simulation orchestrator, weather service, passenger service). The planning service uses its own local factory.
- What is true and usable: the BTS extract is real (filtered from the public T-100 data), and the calibration path in `sim-orchestrator/services/bts_calibration.py` genuinely raises the fidelity of L0 behaviour from L2 data.
- The passenger queue forecast is obtained in `_get_forecast_queues`, passed to `SecuritySystem.drain_all`, and used by `effective_throughput` to determine how many passengers leave `security_queue`. The resulting `airside` transition is written to Neo4j and emitted as an event. The forecaster therefore writes back into operational L0 behaviour even though its implementation technique is predictive ML.

### Decision taken

The camera-ready paper takes the prototype route. The flawed planning predictors remain in the repository but are explicitly identified as prototypes; no MAE, RMSE, or AUC is presented as evidence. The operational queue forecaster is classified as an embedded L0 feedback component, while the scenario engine, anomaly detector, optimisation, appraisal, and gated command path remain the concrete L3 examples.

## 3. Consistency fixes

| Item                                                      | Where                      | Status   | Completion note |
| --------------------------------------------------------- | -------------------------- | -------- | --------------- |
| Remove "more than fifty sprints"                          | Abstract, intro, Section 4 | **Done** | Removed throughout, including the rewritten evaluation. |
| Rename "architectural invariants" to "runtime invariants" | Sections 4, 5              | **Done** | Runtime rules and the distinct fidelity-preservation architectural invariant are now separated. |
| Adapt Section 7 to the new RQ2                            | Section 7                  | **Done** | Discussion answers the aligned RQ2 and states the verification limits. |
| Describe the mid-project audit early                      | Section 4                  | **Done** | Audit and human-correction perimeter appear in Section 4. |
| "Nine microservices" vs "ten directories"                 | Sections 1, 5, 6           | **Done** | Standardised to nine FastAPI domain services plus one API gateway. |
| "Hexagonal boundaries" is undefined                       | Section 7                  | **Done** | Undefined term removed. |
| "Productivity and defect trends" are not reported         | Section 7                  | **Done** | Replaced by an explicit statement that no causal productivity or defect-rate effect can be inferred. |
| "Mutation-style guards" are not described                 | Sections 4, 7              | **Done** | Replaced by concrete cross-service contract and fidelity regression tests. |
| "Causal chain traced in Section 6" has no trace           | Fig. 4 caption             | **Done** | Unsupported trace claim removed; the cost-dashboard caption now states only the demonstrated event-consumption behaviour. |
| Typo "agggregating"                                       | Section 6                  | **Done** | Removed in the evaluation rewrite. |
| Queue forecasting appears under L3 despite L0 write-back | Sections 1, 3 and 5        | **Done** | Removed the queue forecaster from L3, labelled it as an embedded L0 feedback component with its write-back disclosed, and changed Table 1 from “forecast horizons” to “scenario horizons”. |

## 4. Final camera-ready follow-up

| Item | Status | Completion note |
| ---- | ------ | --------------- |
| Restore Kafka and graph-database citations | **Done** | Restored `kreps2011` and `angles2008` in the Section 5 stack description. |
| Verify `sethi2017` | **Done** | Verified against the publisher record: `refs.bib` contains Sethi and Sarangi, *Journal of Electrical and Computer Engineering* (2017), article 9324035, DOI `10.1155/2017/9324035`. |
| Remove spaces from Annex asset names | **Done** | Renamed the referenced assets to `data-sources-dashboard.png` and `cost-dashboard.png`; the former is now used in the main evaluation section and the latter remains in the Annex. |
| Recheck the Introduction after the Section 6 rewrite | **Done** | The contribution list still describes the blast-radius analysis and conformance audit, and the roadmap points to the combined Discussion and Conclusion section. The concrete L3 list was aligned with Section 5. |
| Apply the venue page policy | **Done** | The 12-page limit is tracked for abstract, introduction, and main text only; references and Annex are excluded. One L2 implementation screenshot was restored to the main evaluation section as direct implementation evidence. |

## 5. Overall-review pass

| Item | Status | Completion note |
| ---- | ------ | --------------- |
| Give Table 1 an L3 spatial example | **Done** | Used “asset-level decisions”, which is implemented through terminal/gate/runway/flight-specific scenarios and recommendations. The text explains why unimplemented 3D visualisation belongs to L1/L2 unless used as a decision interface. |
| Calibrate definitive language for ongoing work | **Done** | Abstract, Sections 3 and 5, and the conclusion now call EVSK an ongoing research prototype, distinguish conformance targets from guarantees, and identify incomplete approval/command coverage. |
| Replace DOI reproducibility link | **Done** | Removed the Zenodo DOI sentence and retained only the GitHub project link requested by the authors. |
| Reposition Figure 2 | **Done** | The source-selection screenshot now appears at the audit/results transition, at a size that preserves legibility without displacing the section opening. |
| Extend Sections 6 and 7 | **Done** | Added the audit protocol, four recorded dimensions, per-path results, BTS counterexample, executable-check scope, qualified RQ answers, comparison limits, transfer argument, and concrete future work. |
| Verify all reviewer questions | **Done** | The manuscript now addresses contribution identity, fidelity definition and motivation, commit-ID reproducibility concern, generalisability, human correction perimeter, data integrity and approval gating, UML notation, comparison with prior architectures, and a concrete failure/counterexample path. |
| Start references on a new page | **Done** | The main text and acknowledgments end on page 12; References starts on a clean page 13; Annex follows after the bibliography. |
| Correct Table 1 caption and L1 temporal entry | **Done** | The caption now describes the three fidelity dimensions rather than a nonexistent EVSK column; L1 temporal fidelity is “unchanged (discrete)” while travel and transfer times remain behavioural. |
| Clarify synthetic data versus live feeds | **Done** | The Introduction and methodology now state that operational entities and ground truth are synthetic except for opt-in L2 live ADS-B and METAR feeds. |
| Add quantitative Git blast-radius metrics | **Done** | Added a reproducible `article/scripts/blast_radius_metrics.py` analysis with declared changeset anchors and path scopes. Section 6 reports unique scoped files / pre-existing files modified / components touched as 14/6/5 (L1), 17/9/7 (L2), 7/5/3 (BTS), and 35/12/6 (L3). |

## 6. Suggested order of work

1. Decide the planning-model route (fix or prototype).
2. Run the repository analysis for Section 6 (items 8 to 10), then rewrite that section.
3. Confirm the L2 to L3 checks that actually exist (item 11).
4. Write the Related Work paragraphs (items 12 and 13).
5. Redraw the diagrams (item 14).
6. Clear the consistency fixes and the camera-ready admin (item 16).

## 7. Camera-ready verification

- `A_Layered_Architecture_for_Digital_Twins_with_Progressive_Fidelity.pdf` compiles without undefined references, LaTeX errors, or overfull boxes.
- The PDF is 18 pages. Under the venue rule, the counted abstract, main text, and acknowledgments occupy pages 1--12; References starts on page 13; the Annex starts on page 15.
- All 18 rendered pages were visually inspected for clipping, overlap, and legibility.
- Contract, planning-fidelity, approval-queue, and autonomous-routing tests: **66 passed**.
