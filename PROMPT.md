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

- The website is slow, improve performance.
- Make the website more nice and modern: colors, fonts, layout, responsiveness etc.
- All flights are stuck at boarding and get cancelled in the end because they aren't being filled with baggages and passengers. Fix the logic to make sure flights get filled and take off.
- Arrived flights with 0 passengers and baggages are showing as "AT GATE" instead of "ARRIVED". Fix the logic to show them as "ARRIVED".
- Passenger repartition is weird and the carroussel aren't being used:
  Airport Heatmap
  check-in
  security
  airside
  gate
  check-in-A
  1118 pax
  559% · 0 free
  security-A
  569 pax
  474.2% · 0 free
  airside-A
  740 pax
  92.5% · 60 free
  gate-A01
  1187 pax
  659.4% · 0 free
  check-in-B
  1905 pax
  952.5% · 0 free
  security-B
  242 pax
  201.7% · 0 free
  airside-B
  782 pax
  97.8% · 18 free
  gate-B01
  1514 pax
  841.1% · 0 free
  check-in-C
  1462 pax
  731% · 0 free
  security-C
  37 pax
  30.8% · 83 free
  airside-C
  555 pax
  69.4% · 245 free
  gate-C01
  740 pax
  411.1% · 0 free
  Arrival Carousels
  carousel-1
  0 pax
  0% · 150 free
  carousel-2
  0 pax
  0% · 150 free
  carousel-3
  0 pax
  0% · 150 free
  carousel-4
  0 pax
  0% · 150 free
  carousel-5
  0 pax
  0% · 150 free
  carousel-6
  0 pax
  0% · 150 free
  Calm
  Low
  Moderate
  Busy
  High
  Near Cap

- In Ground Op tab, there is a weird B icon over Terminal C
