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

The current task is "Add cost models and capacity planning scenarios". Your mission is to implement:

- cost-service-1 | Traceback (most recent call last):
  cost-service-1 | File "/usr/local/lib/python3.11/site-packages/starlette/routing.py", line 694, in lifespan
  cost-service-1 | async with self.lifespan_context(app) as maybe_state:
  cost-service-1 | File "/usr/local/lib/python3.11/contextlib.py", line 210, in **aenter**
  cost-service-1 | return await anext(self.gen)
  cost-service-1 | ^^^^^^^^^^^^^^^^^^^^^
  cost-service-1 | File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 216, in merged_lifespan
  cost-service-1 | async with original_context(app) as maybe_original_state:
  cost-service-1 | File "/usr/local/lib/python3.11/contextlib.py", line 210, in **aenter**
  cost-service-1 | return await anext(self.gen)
  cost-service-1 | ^^^^^^^^^^^^^^^^^^^^^
  cost-service-1 | File "/app/main.py", line 56, in lifespan
  cost-service-1 | await wait_for_neo4j(max_attempts=12, delay_s=5)
  cost-service-1 | File "/app/db/neo4j.py", line 37, in wait_for_neo4j
  cost-service-1 | logger.warning("neo4j not ready", attempt=attempt, error=str(exc))
  cost-service-1 | File "/usr/local/lib/python3.11/logging/**init**.py", line 1501, in warning
  cost-service-1 | self.\_log(WARNING, msg, args, \*\*kwargs)
  cost-service-1 | TypeError: Logger.\_log() got an unexpected keyword argument 'attempt'
  Container arthur-airport-cost-service-1 Error dependency cost-service failed to start
  Container arthur-airport-sim-orchestrator-1 Error dependency sim-orchestrator failed to start
  Container arthur-airport-kafka-1 Error dependency kafka failed to start

- Improve all tests, focus on checking of they do everything we want and not only part of it. It should be a check of the behaviour, not technical details or basic edge cases. So we can always be sure that we don't break something when we do a change in the future.

- Refactor flexible data sources logic to make it more maintainable and extensible, and add more test coverage on it.
  Basically we should be able to have different themes, then different data sources for 1 theme, and then adapters, quick use in the services, common display & compare tools.

- Make the code more elegant and maintainable in general, by refactoring, improving the structure, adding comments, improving naming etc. without changing the behaviour. We want to keep the codebase clean and maintainable to make it easier to work on in the future.
