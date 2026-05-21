# Example prompt to use after creating a new markdown with tasks

Before doing any edit, do this:

- READ all SPEC and skill files.
- READ scripts/ README.md if it exists.
- READ ROADMAP.md fully.
- READ all md files in docs/lessons-learned
- NEVER implement any roundabout fix. For any very complex thing, write a plan file in docs/lessons-learned/ and then implement it step by step.
- ALWAYS use fish ready command (so use bash -c when necessary) to run commands in the terminal, and make sure to use the right syntax for it.
- ALWAYS take the elegant solution, even if it takes more time. Don't do quick and dirty fixes.
- ALWAYS run tests and validate along the way the behaviour of the services by rebuilding the container, doing curls requests etc.
- ALWAYS keep interesting scripts you write for testing for example to evaluate flights, passengers etc. in this project folder in the `scripts/` folder with a helper_prefix, and document how to use them in a README in the folder.
- ALWAYS fix all bugs you see along the way, even if they are not in the original plan. If you see something that can be improved, do it.
- ALWAYS save into a tmp file the output of the logs or the curl requests to make your processing easier.
- ALWAYS clean any temporary file you created during the process.
- ALWAYS test services locally with docker-compose before pushing, and make sure to check the logs of the services to understand their behaviour.
- NEVER commit any temporary file.
- NEVER write code that you don't understand. If you don't understand something, ask for help or write a plan to investigate and understand it before writing the code.
- NEVER use sleep in terminal commands, precise to the user to wait before accepting the command.
- ALWAYS write a final summary of the changes you made, the issues you fixed, the tests you ran and the results you got in a md file in docs/lessons-learned/.
- ALWAYS mark issues as completed in the relevant file if needed.
- ALWAYS run the tests necessary to pass Github CI/CD at the end: ruff check, npm build etc.
- ALWAYS use light mode for local development to speed up image building. Only use full mode if need to test the full integration.
- ALWAYS correct all bugs found, even those unrelated to the current task, to keep the codebase clean and maintainable.
- ALWAYS update data schemas in necessary files when adding new functionnalities (.md, mermaid files etc.).

The current task is "Stabilize architecture, review new functionnalities and correct bugs and gaps". Your mission is to implement:

- The cost page never get fed with costs even after letting the simulation runs for some time. This is a critical issue to fix as it prevents the cost page from working and being useful.
- BTS data doesn't fully fit the capacity of our airport right? so we might get absurd gate time etc. no? If yes, add a warning to the user in the data source page and allow him to set a gap. You should make it nice and not too info crowded in the data soruce card, maybe with a tooltip?
- The Comparison for passenger and incident should be like the weather one... it should be inside the card and use common components.