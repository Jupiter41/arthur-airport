# Example Prompt (Post-Setup Task Execution Guide)

Before doing any edit, follow these steps:

## 1. Required Reading (Mandatory)

- Read all `SPEC` and skill files.
- Read `scripts/README.md` if it exists.
- Read `ROADMAP.md` fully.
- Read all `.md` files in `docs/lessons-learned/`.

---

## 2. Core Rules (Non-Negotiable)

- NEVER implement a roundabout or hacky fix.
  - For complex issues, first write a plan file in `docs/lessons-learned/`, then implement step by step.
- ALWAYS prefer the elegant solution, even if it takes more time.
- NEVER do quick and dirty fixes.

---

## 3. Execution Requirements

- ALWAYS use a fish-compatible command style (use `bash -c` when necessary).
- ALWAYS run tests and validate behavior during development:
  - Rebuild containers
  - Execute curl requests
  - Validate service behavior
- ALWAYS keep useful scripts in the `scripts/` folder:
  - Use a `helper_` prefix
  - Document usage in a README inside the folder
- ALWAYS fix all bugs encountered, even if not part of the original task.
- ALWAYS improve design or code quality when possible.

---

## 4. Debugging & Safety Rules

- ALWAYS save logs or curl outputs into temporary files for easier processing.
- ALWAYS clean up temporary files after use.
- NEVER commit temporary files.
- NEVER write code you do not fully understand.
  - If unclear, write a plan to investigate first.
- NEVER use `sleep` in terminal commands.
  - Instead, explicitly instruct the user to wait if needed.

---

## 5. Documentation Requirements

- ALWAYS write a final summary of changes in:
  - `docs/lessons-learned/`
- The summary must include:
  - Changes made
  - Issues fixed
  - Tests executed
  - Results obtained
- ALWAYS mark completed items in relevant files when applicable.

---

## 6. CI/CD Validation (Mandatory at End)

Always run:

- `ruff check`
- `npm build`
- Any other required CI/CD validation steps

---

## 7. Mission: Full Audit & Verification

1. Perform a deep audit of all items marked as **“done”** in `ROADMAP.md` (or "implemented" in lessons-learned files).
2. Do NOT trust status labels — verify everything via:
   - Code review
   - Spec comparison
   - Functional testing
   - Edge case validation

---

## 8. Identify Issues

Look for:

- Bugs
- Missing functionality
- Logical inconsistencies
- Deviations from specifications
- Performance or design issues

---

## 9. Deliverables

- Write a comprehensive fix plan in `docs/lessons-learned/`
- Implement all fixes systematically
- Validate each fix thoroughly
- Write a final report including:
  - Summary of changes
  - Issues fixed
  - Tests run
  - Results

---

## 10. Mindset

- Be skeptical: “done” may be wrong.
- Be methodical: always verify before acting.
- Be thorough: no shallow checks.
- Be clean: no shortcuts or hidden technical debt.
