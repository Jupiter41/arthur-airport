# BTS T-100 Sample Data

The Bureau of Transportation Statistics (BTS) T-100 Domestic/International
Segment dataset contains monthly aggregate passenger, seat and departure
counts for every commercial flight segment touching a U.S. airport.

This folder ships a small **sample** so the digital twin can demonstrate the
"historical passenger" data source without requiring an out-of-band download.

---

## Files

| File                  | Description                                        |
| --------------------- | -------------------------------------------------- |
| `T100_sample.csv`     | 24-row sample (12 months × 2 directions × 1 hub)   |

The columns match the canonical T-100 segment header so the same parser
handles both the sample and the full dataset.

| Column                | Notes                                                            |
| --------------------- | ---------------------------------------------------------------- |
| `ORIGIN`              | IATA origin code                                                 |
| `DEST`                | IATA destination code                                            |
| `UNIQUE_CARRIER`      | IATA airline code                                                |
| `DEPARTURES_PERFORMED`| Monthly departures actually flown                                |
| `SEATS`               | Monthly available seats (sum across all departures)              |
| `PASSENGERS`          | Monthly passengers carried                                       |
| `MONTH`               | 1–12                                                             |
| `YEAR`                | 4-digit year                                                     |

---

## Downloading the full dataset

Source: <https://www.transtats.bts.gov/Tables.asp?DB_ID=111>

The portal does not expose a stable REST endpoint; the recommended approach
is the manual filtered CSV download:

1. Open the **T-100 Segment (All Carriers)** table.
2. Select the columns above.
3. Pick the year(s) and geography you need.
4. Download as CSV and place under `data/bts/T100_<year>.csv`.

Then point the passenger-service at the file:

```bash
PASSENGER_BTS_FILE=/app/data/bts/T100_2023.csv \
PASSENGER_SOURCE=bts_historical \
docker compose up passenger-service
```

The runtime switcher in the dashboard (`Data Sources → Passenger Flow → BTS
Historical`) will reload the active CSV without a service restart.
