# BTS T-100 Integration

## What is BTS?

The **Bureau of Transportation Statistics** (BTS) is a division of the U.S.
Department of Transportation responsible for collecting, analysing, and
publishing transportation statistics. Their datasets are the canonical source
of truth for U.S. commercial aviation activity.

Website: <https://www.bts.gov>

---

## T-100 Dataset

The **T-100 Domestic/International Segment** dataset contains monthly aggregate
statistics for every commercial flight segment touching a U.S. airport:

| Column                 | Description                                         |
| ---------------------- | --------------------------------------------------- |
| `ORIGIN`               | IATA origin airport code                            |
| `DEST`                 | IATA destination airport code                       |
| `UNIQUE_CARRIER`       | IATA airline code                                   |
| `DEPARTURES_PERFORMED` | Monthly departures actually flown                   |
| `SEATS`                | Monthly available seats (sum across all departures)  |
| `PASSENGERS`           | Monthly passengers carried                          |
| `MONTH`                | 1–12                                                |
| `YEAR`                 | 4-digit year                                        |

Source: <https://www.transtats.bts.gov/Tables.asp?DB_ID=111>

---

## How BTS data flows through the architecture

```
┌──────────────────┐
│  data/bts/*.csv  │   Raw T-100 CSV files (sample or full download)
└────────┬─────────┘
         │ read on startup
         ▼
┌──────────────────────────────────────────────────────────────┐
│  sim-orchestrator  (BTSCalibrationData)                      │
│  services/sim-orchestrator/services/bts_calibration.py       │
│                                                              │
│  • Reads T-100 CSV                                           │
│  • Calibrates schedule generator destination weights          │
│  • Sets per-route load factors (pax/seats ratio)             │
│  • Output: realistic schedule distribution at startup         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  passenger-service  (BTSPassengerSource)                     │
│  services/passenger-service/services/bts_adapter.py          │
│                                                              │
│  • Reads T-100 CSV                                           │
│  • Disaggregates monthly totals into hourly profiles          │
│  • Provides get_flow_at(sim_time) for passenger flow overlay │
│  • Switchable via REST: POST /passengers/source              │
└──────────────────────────────────────────────────────────────┘
```

### Data source switching

The passenger-service supports runtime switching between data sources:

```bash
# Switch to BTS historical mode
curl -X POST http://localhost:3000/api/v1/passengers/source \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "bts_historical"}'

# Check current source and BTS summary
curl http://localhost:3000/api/v1/passengers/source
curl http://localhost:3000/api/v1/passengers/bts/summary
```

---

## Files in the repository

| Path | Description |
|------|-------------|
| `data/bts/T100_sample.csv` | 24-row sample (12 months × 2 directions × 1 hub) |
| `data/bts/T100_2026.csv` | Full year dataset (if downloaded) |
| `data/bts/README.md` | Dataset documentation and download instructions |
| `services/passenger-service/services/bts_adapter.py` | BTS passenger source adapter |
| `services/sim-orchestrator/services/bts_calibration.py` | Schedule calibration from BTS |

---

## Implementation status

| Feature | Status |
|---------|--------|
| T-100 CSV parser | ✅ Implemented |
| Monthly → hourly disaggregation | ✅ Implemented |
| Schedule calibration (destination weights) | ✅ Implemented |
| Per-route load factor calibration | ✅ Implemented |
| Runtime source switching (REST) | ✅ Implemented |
| BTS flow query endpoint | ✅ Implemented |
| BTS summary endpoint | ✅ Implemented |
| Dashboard Data Sources page integration | ✅ Implemented |
| Multi-year trend analysis | ❌ Not yet |
| Automatic download/refresh | ❌ Not yet (manual CSV download) |

---

## Adding new data

1. Download a T-100 CSV from the BTS portal (see `data/bts/README.md` for steps)
2. Place it under `data/bts/T100_<year>.csv`
3. Set the environment variable: `PASSENGER_BTS_FILE=/app/data/bts/T100_<year>.csv`
4. Restart the passenger-service (or switch source via REST)

The CSV must contain the columns listed above. Both the sample and full
dataset use the same parser.

---

## Limitations

- **U.S. airports only**: T-100 covers segments touching U.S. airports.
  International-only routes are not included.
- **Monthly granularity**: The raw data is monthly aggregates. Hourly profiles
  are synthetically generated using a standard bell-curve distribution.
- **No real-time updates**: BTS data is published with a ~3 month lag.
  The adapter treats it as a static historical overlay.
- **Fictional mapping**: Since KART is a fictional airport, the adapter maps
  T-100 data from a real hub airport to the simulated routes.
