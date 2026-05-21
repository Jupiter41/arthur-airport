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

- I think a few things that were implemented recently disappeared or need to be stabilized. You can explore the recent lessons learned to identify them. For example, the user can't export a scenario in the scenario page and they are super slow to start, in data source there is no comparison thing for BTS & Incident etc.
- The cost page display no cost in any graph. The dashboard should be live (at least some graphs, it's fine if it needs to wait for some plots): user should see revenue/expenses at it goes.
- Allow user to export cost dashboard data as CSV, like in the other pages.
- It's hard to use the cost rate config because it's a small section at the end of the page. Maybe it could be a tooltip openning a modal to select a cost profile or manually edit it.
- Maybe add a tooltip opening a modal for the autonomous panel too, to allow the user to inject a bottleneck/incident and showcase the autonomous recommendations impact.
