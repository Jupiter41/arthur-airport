# SKILL — LightGBM forecasting model
## passenger-service · queue depth prediction

---

## Purpose

Predicts per-terminal security queue depth up to 90 simulated minutes ahead.
Used for two things:
1. **Slowdown factor** — if actual queue > 1.3× forecast, throughput degrades
2. **Dashboard forecast curve** — powers the demand chart in the passenger flow UI

Lives entirely inside `passenger-service`. No other service touches it.

---

## Feature vector

| Feature | Type | Source | Notes |
|---|---|---|---|
| `hour_of_day` | int (0–23) | sim_time | Simulated hour |
| `day_of_week` | int (0–6) | sim_time | 0 = Monday |
| `month` | int (1–12) | sim_time | Simulated month |
| `season` | int (0–3) | derived from month | 0=winter 1=spring 2=summer 3=autumn |
| `weather_category` | int (0–3) | weather.events cache | 0=CAVOK 1=VMC 2=IMC 3=LIFR |
| `flights_departing_next_90min` | int | Neo4j query | Departures from this terminal in next 90 sim-min |
| `expected_pax_next_90min` | float | Neo4j query | Sum of pax_count for those flights |
| `load_factor_avg_today` | float | in-memory running avg | Updated on each SimClockTick |
| `active_incident_in_terminal` | int (0/1) | incidents cache | Any active incident in this terminal |
| `adjacent_terminal_congested` | int (0/1) | local state | Either other terminal has wait > 20 sim-min |
| `is_special_event` | int (0/1) | fixtures/events.json | Event active on current sim day |
| `event_pax_multiplier` | float | fixtures/events.json | 1.0 if no event |

Build the feature dict:

```python
def build_features(terminal: str, sim_time: datetime,
                   context: ForecastContext) -> dict:
    month = sim_time.month
    season = (month % 12) // 3  # 0=winter(Dec-Feb) 1=spring 2=summer 3=autumn

    event = get_active_event(sim_time, terminal)

    return {
        "hour_of_day":                  sim_time.hour,
        "day_of_week":                  sim_time.weekday(),
        "month":                        month,
        "season":                       season,
        "weather_category":             WEATHER_ENCODING[context.weather_category],
        "flights_departing_next_90min": context.flights_next_90[terminal],
        "expected_pax_next_90min":      context.pax_next_90[terminal],
        "load_factor_avg_today":        context.load_factor_today,
        "active_incident_in_terminal":  int(context.incident_active[terminal]),
        "adjacent_terminal_congested":  int(context.adjacent_congested[terminal]),
        "is_special_event":             int(event is not None),
        "event_pax_multiplier":         event.pax_multiplier if event else 1.0,
    }

WEATHER_ENCODING = {"CAVOK": 0, "VMC": 1, "IMC": 2, "LIFR": 3}
```

---

## Training data collection

Every simulated minute, log a training row for each terminal:

```python
@dataclass
class TrainingRow:
    terminal: str
    sim_time: datetime
    features: dict          # feature vector at this sim_time
    target: int             # actual queue_depth at this sim_time

# Stored in-memory as a deque, flushed to /app/training_data/{terminal}.parquet
# every 60 sim-minutes (to avoid memory growth)
from collections import deque
_buffer: deque[TrainingRow] = deque(maxlen=10_000)
```

---

## Model spec

```python
import lightgbm as lgb

FEATURE_COLS = [
    "hour_of_day", "day_of_week", "month", "season",
    "weather_category", "flights_departing_next_90min",
    "expected_pax_next_90min", "load_factor_avg_today",
    "active_incident_in_terminal", "adjacent_terminal_congested",
    "is_special_event", "event_pax_multiplier",
]

def make_model() -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
    )
```

---

## Training pipeline

```python
import pandas as pd
import joblib
from pathlib import Path

MODELS_DIR = Path(os.getenv("MODELS_PATH", "/app/models"))
MODELS_DIR.mkdir(exist_ok=True)

async def retrain(terminal: str):
    """Run in background thread — do not await directly in hot path."""
    parquet_path = Path(f"/app/training_data/{terminal}.parquet")
    if not parquet_path.exists():
        return  # not enough data yet

    df = pd.read_parquet(parquet_path)
    if len(df) < 500:
        return  # need at least 500 rows

    X = df[FEATURE_COLS]
    y = df["target"]

    model = make_model()
    model.fit(X, y,
              eval_set=[(X, y)],
              callbacks=[lgb.log_evaluation(period=50)])

    # evaluate MAE on last 20% of data (temporal split)
    split = int(len(df) * 0.8)
    mae = abs(model.predict(df[FEATURE_COLS].iloc[split:]) -
              df["target"].iloc[split:]).mean()

    # save
    model_path = MODELS_DIR / f"forecast_{terminal}.lgbm"
    joblib.dump(model, model_path)
    print(f"[Forecast] Retrained {terminal}: MAE={mae:.1f} rows={len(df)}")
```

---

## Inference

```python
_models: dict[str, lgb.LGBMRegressor] = {}

def load_models():
    for terminal in ("A", "B", "C"):
        path = MODELS_DIR / f"forecast_{terminal}.lgbm"
        if path.exists():
            _models[terminal] = joblib.load(path)

def predict(terminal: str, features: dict) -> int | None:
    model = _models.get(terminal)
    if model is None:
        return fallback_forecast(features)
    import pandas as pd
    X = pd.DataFrame([features])[FEATURE_COLS]
    pred = model.predict(X)[0]
    return max(0, int(pred))

def fallback_forecast(features: dict) -> int:
    """Day-1 fallback: simple ratio of expected pax."""
    ratio = float(os.getenv("FORECAST_FALLBACK_QUEUE_RATIO", "0.35"))
    return int(features["expected_pax_next_90min"] * ratio)
```

---

## Retraining schedule

```python
_last_retrain_day: int = 0
RETRAIN_EVERY_N_DAYS = int(os.getenv("FORECAST_RETRAIN_EVERY_N_DAYS", "3"))

async def maybe_retrain(sim_day: int):
    if sim_day - _last_retrain_day >= RETRAIN_EVERY_N_DAYS:
        loop = asyncio.get_event_loop()
        for terminal in ("A", "B", "C"):
            await loop.run_in_executor(None, lambda t=terminal: retrain_sync(t))
        load_models()  # hot-reload after retraining
        _last_retrain_day = sim_day
```

Call `maybe_retrain(payload["day_of_sim"])` inside `on_clock_tick`.

---

## Congestion detection

```python
_ticks_over_threshold: dict[str, int] = {"A": 0, "B": 0, "C": 0}
THRESHOLD_MIN = int(os.getenv("SECURITY_CONGESTION_WAIT_THRESHOLD_MIN", "20"))
CONSECUTIVE    = int(os.getenv("SECURITY_CONGESTION_CONSECUTIVE_TICKS", "5"))

def check_congestion(terminal: str, wait_minutes: float,
                     sim_time: datetime) -> bool:
    if wait_minutes > THRESHOLD_MIN:
        _ticks_over_threshold[terminal] += 1
    else:
        _ticks_over_threshold[terminal] = 0

    if _ticks_over_threshold[terminal] >= CONSECUTIVE:
        _ticks_over_threshold[terminal] = 0  # reset after firing
        return True  # caller should emit SecurityCongestionDetected
    return False
```

---

## Gotchas

- **Features must be in the exact same column order at train and predict time.** Always use `FEATURE_COLS` list explicitly when building DataFrames.
- **`joblib.dump/load` is not async-safe.** Always run in `run_in_executor`.
- **LightGBM will silently ignore extra columns** passed to `predict()` — but will crash on missing columns. Guard with `df[FEATURE_COLS]`.
- **Training data grows unboundedly** without the `deque(maxlen=...)` + parquet flush pattern. In a long-running sim, this will OOM the container.
- **The fallback formula is intentionally simple.** Don't make it smarter — the whole point of day 1 fallback is that it's a dumb baseline the ML model should beat.
