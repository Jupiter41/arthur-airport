# Example prompt to use after creating a new markdown with tasks

Before doing any edit, do this:

- READ all SPEC and skill files.
- READ scripts/ README.md if it exists.
- READ ROADMAP.md fully.
- READ all md files in docs/lessons-learned
- NEVER implement any roundabout fix. For any very complex thing, write a plan file in docs/lessons-learned/ and then implement it step by step.
- ALWAYS take the elegant solution, even if it takes more time. Don't do quick and dirty fixes.
- ALWAYS run tests and validate along the way the behaviour of the services by rebuilding the container, doing curls requests etc.
- ALWAYS keep interesting scripts you write for testing for example to evaluate flights, passengers etc. in this project folder in the `scripts/` folder with a helper_prefix, and document how to use them in a README in the folder.
- ALWAYS fix all bugs you see along the way, even if they are not in the original plan. If you see something that can be improved, do it.
- ALWAYS save into a tmp file the output of the logs or the curl requests to make your processing easier.
- ALWAYS clean any temporary file you created during the process.
- NEVER commit any temporary file.
- NEVER write code that you don't understand. If you don't understand something, ask for help or write a plan to investigate and understand it before writing the code.
- NEVER use sleep in terminal commands, precise to the user to wait before accepting the command.
- ALWAYS write a final summary of the changes you made, the issues you fixed, the tests you ran and the results you got in a md file in docs/lessons-learned/.
- ALWAYS mark issues as completed in the relevant file if needed.
- ALWAYS run the tests necessary to pass Github CI/CD at the end: ruff check, npm build etc.

Your mission is to:

1. Perform a deep audit of all items marked as “done” in ROADMAP.md (or as "implemented" in the lessons-learned files).
2. Do not trust the status — verify everything through:
    - Code review
    - Specs comparison
    - Functional testing
    - Edge case validation
3. Identify:
   - Bugs
   - Missing functionality
   - Logical inconsistencies
   - Deviations from specifications
   - Performance or design issues
4. Then:
    - Write a comprehensive fix plan in docs/lessons-learned/
    - Implement all fixes systematically
    - Validate each fix thoroughly
    - Write a final report in docs/lessons-learned/ with:
    - Summary of changes
    - Issues fixed
    - Tests run and results
Key Mindset
    - Be skeptical: assume “done” might be wrong.
    - Be methodical: verify before acting.
    - Be thorough: no shallow checks or fixes.
    - Be clean: no shortcuts, no technical debt, no breaking features or missing functionality.