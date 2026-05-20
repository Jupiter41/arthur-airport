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

The current task is "Stabilize architecture, review new functionnalities and correct bugs and gaps". Your mission is to implement:

- In architecture/DATA_SOURCE.md it's written that BTS historical is not fully implemented yet. Finish to implement it. Adapt all mentions to BTS data with the latest info (how it's used etc.) passenger-service simulation Sim engine Probabilistic passenger generation
  passenger-service bts_historical CSV offline Bureau of Transportation Statistics T-100 segment data (adapter specced, not yet implemented)
- in Git test fail during node & lint while installing dashboard dependencies. Run npm ci
  npm error code EUSAGE
  npm error
  npm error `npm ci` can only install packages when your package.json and package-lock.json or npm-shrinkwrap.json are in sync. Please update your lock file with `npm install` before continuing.
  npm error
  npm error Missing: esbuild@0.27.7 from lock file
  npm error
  npm error Clean install a project
  npm error
  npm error Usage:
  npm error npm ci
  npm error
  npm error Options:
  npm error [--install-strategy <hoisted|nested|shallow|linked>] [--legacy-bundling]
  npm error [--global-style] [--omit <dev|optional|peer> [--omit <dev|optional|peer> ...]]
  npm error [--include <prod|dev|optional|peer> [--include <prod|dev|optional|peer> ...]]
  npm error [--strict-peer-deps] [--foreground-scripts] [--ignore-scripts] [--no-audit]
  npm error [--no-bin-links] [--no-fund] [--dry-run]
  npm error [-w|--workspace <workspace-name> [-w|--workspace <workspace-name> ...]]
  npm error [-ws|--workspaces] [--include-workspace-root] [--install-links]
  npm error
  npm error aliases: clean-install, ic, install-clean, isntall-clean
  npm error
  npm error Run "npm help ci" for more info
  npm error A complete log of this run can be found in: /home/runner/.npm/\_logs/2026-05-19T18_07_22_730Z-debug-0.log
  Error: Process completed with exit code 1.
- New services were implemented (cost and beginning of planning) but their architecture is not solid enough spec wise: edit/add/updated documentation files, architecture files, SPEC files to make sure the architecture is solid and well documented. Don't base yourself on what's done but on what should be done, and then identify gaps and bugs and fix them.
- Identify and solve redundant logic and code duplication in the codebase, especially between the different services. For example, if you see that there are similar functions or logic in passenger-service and flight-service, try to abstract them into a common library or service to avoid duplication and improve maintainability.
- Review the implementation of the new functionalities (cost etc.).
