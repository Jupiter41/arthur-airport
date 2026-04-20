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

Your mission is to:

1. **Shared idempotency module** — The FIFO eviction logic is now duplicated across 3
   services. Extract to a shared `_common/idempotency.py` module.

2. **Structured logging** — All services use plain-text logging. Switching to JSON structured
   logging (e.g., `python-json-logger`) would improve log aggregation in Grafana/Loki.

3. **Consumer health checks** — Kafka consumers run in background threads with no health
   signal. If a consumer thread dies, the service continues serving HTTP but processes no
   events. Add a liveness check (e.g., last-processed timestamp exposed via `/health`).

4. **Schema registry** — Event schemas are implicit (Python dicts). Adding a schema registry
   (or at least Pydantic models for all event types) would catch envelope mismatches at
   produce time rather than at consume time.

5. **Neo4j connection pooling tuning** — Default driver settings may not be optimal for the
   burst-heavy access pattern during high-speed simulation ticks.

6. **WebSocket reconnection backoff** — The dashboard WebSocket reconnects on a fixed
   interval. Implementing exponential backoff with jitter would reduce thundering-herd
   reconnection storms.

7. **Test coverage for analysis-service** — Currently has no unit or integration tests.
   The bottleneck detection, recommendation engine, and anomaly detector are untested.
