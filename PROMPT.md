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
- NEVER commit any temporary file.
- NEVER write code that you don't understand. If you don't understand something, ask for help or write a plan to investigate and understand it before writing the code.
- NEVER use sleep in terminal commands, precise to the user to wait before accepting the command.
- ALWAYS write a final summary of the changes you made, the issues you fixed, the tests you ran and the results you got in a md file in docs/lessons-learned/.
- ALWAYS mark issues as completed in the relevant file if needed.
- ALWAYS run the tests necessary to pass Github CI/CD at the end: ruff check, npm build etc.

Your mission is to:

- Implement all the gaps still not done from ROADMAP.md, for example the Gap 4.
- The world page isn't in 3D because it uses the Leaflet fall back but my MAPBOX token is present in .env. In 2D and 3D planes icons should be a plane icon, not a point. When user click on one precise the info of the plane
- Sometimes the times in departure time column are stroke through and use orange/red whereas estimated = scheduled.
- flight-service-1 | 2026-04-02 07:30:57,542 [neo4j.notifications] WARNING: Received notification from DBMS server: <GqlStatusObject gql_status='01N52', status_description='warn: property key does not exist. The property `arrival_estimated_time` does not exist
- In the passengers page, I think it would be good to add an estimated waiting time with the percentage capacity used.
- I think it would be nice to show more the link flight/passenger/baggage in the terminal pages.
