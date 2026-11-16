# UI external acceptance

Updated 2026-11-16. The implementation checklist is archived at
[UI_TODO.md](../../archive/UI_TODO.md). Engineering checks and their actual
limits are recorded in [UI_VALIDATION.md](UI_VALIDATION.md). These tasks remain
open; archiving the implementation checklist does not complete them.

## Manual accessibility

- [ ] Test actual browser zoom at 200% on every primary route in a browser with
  working zoom controls. Record browser/version, viewport and zoom setting;
  inspect navigation, essential actions, dialogs, inspectors and bottom content.
  The available in-app browser ignored zoom shortcuts. The completed 720×450
  equivalent-layout check is useful reflow evidence, not actual zoom evidence.
- [ ] Complete a manual WCAG 2.2 AA review, including focus order/obscuration,
  accessible names/states, error identification, non-text contrast, hover/focus
  content and table/chart/map alternatives. Exercise alternate tabs, dialogs,
  expanded content, loading/error states and operator-only controls.
- [ ] Test representative monitoring and planning workflows with a screen
  reader and keyboard. Record the assistive technology/browser combination.
  DOM contrast/label measurements do not substitute for these checks.

References: [contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[target size and exceptions](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html),
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html).

## Formative usability session

Recruit people unfamiliar with the app. Use only a synthetic test airport and
isolated experiment data. Explain the task without naming the control to use;
do not coach before recording the first attempt. Record the first meaningful
action, elapsed time, completion, wrong turns, assistance and the participant's
explanation. Agent walkthroughs are engineering checks, not human sessions.

| Task | Setup | Proposed acceptance |
| --- | --- | --- |
| Identify the top issue | Open Overview with a known active exception | Correct issue and reason within 10 seconds |
| Find a known delayed flight and gate | Supply a loaded synthetic flight number | Reach its details in two interactions using search |
| Locate terminal congestion | Start on Overview with a known queue exception | Identify terminal, wait and observation time; retain scope across views |
| Explain action status | Provide recorded proposed/queued/executed/awaiting-measurement decisions | Distinguish dispatch from owner-confirmed execution |
| Find an outcome | Provide a recorded measured or explicitly unmeasurable decision | Explain observed versus attributed change and missing evidence |
| Create an isolated experiment | Start in Planning with operator access and a known baseline | Change one lane, run, compare, reopen results; explain why the shared airport was unaffected |

- [ ] Run the six tasks and record results below.
- [ ] Validate the time/interaction targets with unfamiliar participants.
- [ ] Validate that participants distinguish queued/executed/measured states
  and isolated experiments/shared-airport changes.
- [ ] If a before/after study is commissioned, render the pre-redesign revision
  under the same viewport, task and synthetic dataset. Current-state images are
  not an original baseline.

Record one row per participant/task; use a non-identifying participant label.

| Participant | Task | Completed | Seconds | Interactions | Wrong turns | Assistance | Interpretation / follow-up |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Not yet run | — | — | — | — | — | — | — |
