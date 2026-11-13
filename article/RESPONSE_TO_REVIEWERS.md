# Response to Reviewers

## Reviewer A

- **Relevance, claim integrity, and identification:** Thank you for the positive assessment. No specific revision was required.
- **No AI/ML contribution / remove LLM claims:** Addressed. LLM framing was removed from the abstract, and the manuscript now states that neither agent performance nor a new machine-learning method is a contribution. Existing ML components are described only as capabilities of the EVSK prototype.
- **The problem and contribution were unclear:** Addressed in the Introduction. EVSK is an implemented, ongoing research prototype used as a case-study instrument. The contribution is the fidelity-preserving layered architecture and its empirical conformance analysis, not merely the implementation of an airport application.
- **Commit IDs are insufficient for reproducibility:** Addressed. The evaluation now studies four upgrade paths through specifications, contracts, consumers, lower-layer changes, and tests. A reproducible script adds path-scoped Git metrics, while the public GitHub repository provides the underlying evidence.
- **The applicability beyond EVSK was unclear:** Addressed. Section 3 maps the same ordering of event state, spatial representation, observed data, and decisions to hospitals, ports, manufacturing, and urban mobility. Section 7 also states that transfer remains to be validated in another domain.
- **Fidelity was not defined or motivated:** Addressed in the Introduction and Section 3. Fidelity is defined along spatial, temporal, and behavioural dimensions, and its importance is linked to more reliable feedback and decision making without destabilising existing capabilities.
- **Gate scoring criterion:** No manuscript-specific action was possible because this appears to concern the review rubric rather than paper content. The paper now explains its own L2--L3 approval gate in detail.

## Reviewer B

- **No AI/ML contribution:** Agreed. The revised manuscript does not claim a new AI/ML contribution; coding assistance is treated only as development context.
- **Human intervention around coding assistants was insufficiently bounded:** Addressed in Section 4. Humans define and approve specifications, contracts, and hard rules; review every change; and correct locally plausible outputs that violate architectural boundaries. Three concrete audit findings illustrate this perimeter.
- **Approval-gate triggers and protection against noisy or poisoned data were unclear:** Addressed in Section 3.4. The revision describes adapter parsing and filtering, canonical event envelopes, REST validation, deduplication, confidence-based routing, approver roles, and the limited command mappings currently supported. It also explicitly identifies missing provenance scoring, uniform plausibility checks, runtime schema validation, and durable approval storage as future work.
- **Large commit and file-count statistics had unclear value:** Addressed. Raw commit-size statistics were replaced by upgrade-path analysis. Section 6 records contract, consumer, and lower-layer effects and reports automated path-scoped counts only as supporting blast-radius evidence.
- **The architecture lacked standard UML notation:** Addressed in Fig. 1 using UML-style components and provided-interface notation. The text explains that this makes dependencies reviewable, but does not claim that UML notation improved coding-assistant performance.
- **Comparison with existing architectures was insufficient:** Addressed in Related Work. The manuscript compares the proposed invariant with ISO 23247, Tao's five-dimensional model, and a three-tier IoT architecture, and gives a concrete weather-event coupling example showing the type of restructuring the invariant prevents.
- **Were alternative architectures implemented or quantitatively evaluated?** No. This is now stated explicitly as a limitation. EVSK was not reimplemented under the comparison architectures, so comparative superiority cannot be inferred; such quantification would require comparable longitudinal implementations.
- **General calibration and transferability:** Addressed. Claims are limited to contract preservation in one retrospective, synthetic case, and the conclusion identifies second-domain validation as future work.
- **Gate scoring criterion:** No manuscript-specific action was possible because this appears to concern the review rubric. The revised paper nevertheless clarifies the architecture's approval-gate mechanism and limitations.
