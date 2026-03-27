# From repo root
mkdir -p data/ourairports data/openflights data/weather

# ── OurAirports ───────────────────────────────────────────────────────────────
BASE="https://davidmegginson.github.io/ourairports-data"

curl -o data/ourairports/airports.csv             "$BASE/airports.csv"
curl -o data/ourairports/runways.csv              "$BASE/runways.csv"
curl -o data/ourairports/airport-frequencies.csv  "$BASE/airport-frequencies.csv"
curl -o data/ourairports/navaids.csv              "$BASE/navaids.csv"
curl -o data/ourairports/countries.csv            "$BASE/countries.csv"
curl -o data/ourairports/regions.csv              "$BASE/regions.csv"
curl -o data/ourairports/airport-comments.csv     "$BASE/airport-comments.csv"

# ── OpenFlights ───────────────────────────────────────────────────────────────
BASE="https://raw.githubusercontent.com/jpatokal/openflights/master/data"

curl -o data/openflights/airlines.dat  "$BASE/airlines.dat"
curl -o data/openflights/routes.dat    "$BASE/routes.dat"
curl -o data/openflights/planes.dat    "$BASE/planes.dat"

# ── IEM Mesonet — 30-day METAR history ────────────────────────────────────────

BASE="https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

START=$(date -u -d "30 days ago" +"%Y %m %d")
END=$(date -u +"%Y %m %d")

read Y1 M1 D1 <<< "$START"
read Y2 M2 D2 <<< "$END"

curl -o data/weather/EGLL_30days.csv \
"$BASE?station=EGLL&data=all&tz=UTC&format=onlycomma&latlon=no&year1=$Y1&month1=$M1&day1=$D1&year2=$Y2&month2=$M2&day2=$D2"

curl -o data/weather/LFPG_30days.csv \
"$BASE?station=LFPG&data=all&tz=UTC&format=onlycomma&latlon=no&year1=$Y1&month1=$M1&day1=$D1&year2=$Y2&month2=$M2&day2=$D2"