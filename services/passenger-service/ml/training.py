"""ML training pipeline — deque buffer + parquet flush + LightGBM training.

Training starts after 3 simulated days. Retrains every 3 days.
Model saved to /app/models/forecast_{terminal}.lgbm.
"""

import asyncio
import logging
import os
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import pandas as pd

from ml.features import FEATURE_COLS

logger = logging.getLogger(__name__)

MODELS_DIR = Path(os.getenv("MODELS_PATH", "/app/models"))
TRAINING_DIR = Path(os.getenv("TRAINING_DATA_PATH", "/app/training_data"))
RETRAIN_EVERY_N_DAYS = int(os.getenv("FORECAST_RETRAIN_EVERY_N_DAYS", "3"))
MIN_TRAINING_ROWS = 500

# In-memory training buffers per terminal
_buffers: dict[str, deque] = {
    "A": deque(maxlen=10_000),
    "B": deque(maxlen=10_000),
    "C": deque(maxlen=10_000),
}

_last_retrain_day: int = 0
_last_flush_hour: int = -1


def make_model() -> lgb.LGBMRegressor:
    """Create a LightGBM regressor with tuned hyperparameters for queue depth prediction."""
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
        verbose=-1,
    )


def add_training_row(terminal: str, features: dict, target: int, sim_time: datetime) -> None:
    """Add a training row to the in-memory buffer."""
    row = {**features, "target": target, "sim_time": sim_time.isoformat()}
    _buffers[terminal].append(row)


def flush_to_parquet(terminal: str) -> None:
    """Flush buffer to parquet file. Appends to existing data."""
    buf = _buffers[terminal]
    if not buf:
        return

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = TRAINING_DIR / f"{terminal}.parquet"

    rows = list(buf)
    df_new = pd.DataFrame(rows)

    if parquet_path.exists():
        df_old = pd.read_parquet(parquet_path)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new

    # Keep buffered rows and the previous file intact on failed writes.
    df = df.drop_duplicates(subset=["sim_time"], keep="last").sort_values("sim_time")
    with tempfile.NamedTemporaryFile(dir=TRAINING_DIR, suffix=".parquet", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        df.to_parquet(temporary, index=False)
        os.replace(temporary, parquet_path)
    finally:
        temporary.unlink(missing_ok=True)
    for _ in rows:
        buf.popleft()
    logger.debug("Flushed %d rows for terminal %s → %s", len(df_new), terminal, parquet_path)


def maybe_flush(sim_time: datetime) -> None:
    """Flush buffers every 60 sim-minutes to avoid memory growth."""
    global _last_flush_hour
    current_hour = sim_time.hour
    if current_hour != _last_flush_hour:
        _last_flush_hour = current_hour
        for terminal in ("A", "B", "C"):
            flush_to_parquet(terminal)


def retrain_sync(terminal: str) -> float | None:
    """Synchronous retrain — run in executor thread. Returns MAE or None."""
    parquet_path = TRAINING_DIR / f"{terminal}.parquet"
    if not parquet_path.exists():
        logger.info("No training data for terminal %s", terminal)
        return None

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        logger.error("Failed to read parquet for %s: %s", terminal, e)
        return None

    if len(df) < MIN_TRAINING_ROWS:
        logger.info(
            "Not enough training data for %s: %d rows (need %d)",
            terminal, len(df), MIN_TRAINING_ROWS,
        )
        return None

    # Ensure all feature cols exist
    for col in FEATURE_COLS:
        if col not in df.columns:
            logger.error("Missing feature column '%s' in training data for %s", col, terminal)
            return None

    if "sim_time" not in df or "target" not in df:
        logger.error("Missing target or simulation time for %s", terminal)
        return None
    # Equal simulation timestamps must not straddle the holdout boundary.
    df = df.assign(sim_time=pd.to_datetime(df["sim_time"], utc=True, errors="coerce"))
    df = df.dropna(subset=["sim_time", "target", *FEATURE_COLS])
    df = df.sort_values("sim_time").drop_duplicates(subset=["sim_time"], keep="last")
    if len(df) < MIN_TRAINING_ROWS:
        return None
    split = int(len(df) * 0.8)
    model = make_model()
    model.fit(df[FEATURE_COLS].iloc[:split], df["target"].iloc[:split])

    # The last 20% are future observations, never passed to fit().
    y_pred = model.predict(df[FEATURE_COLS].iloc[split:])
    y_true = df["target"].iloc[split:]
    mae = abs(y_pred - y_true).mean()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"forecast_{terminal}.lgbm"
    with tempfile.NamedTemporaryFile(dir=MODELS_DIR, suffix=".lgbm", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        joblib.dump(model, temporary)
        os.replace(temporary, model_path)
    finally:
        temporary.unlink(missing_ok=True)

    logger.info(
        "[Forecast] Retrained %s: MAE=%.1f rows=%d → %s",
        terminal, mae, len(df), model_path,
    )
    return mae


async def maybe_retrain(sim_day: int) -> bool:
    """Check if retraining is needed. Returns True if retrained."""
    global _last_retrain_day

    if sim_day < RETRAIN_EVERY_N_DAYS:
        return False

    if sim_day - _last_retrain_day < RETRAIN_EVERY_N_DAYS:
        return False

    logger.info("Starting model retraining (sim_day=%d)", sim_day)

    # Flush all remaining buffer data first
    for terminal in ("A", "B", "C"):
        flush_to_parquet(terminal)

    loop = asyncio.get_event_loop()
    trained = False
    for terminal in ("A", "B", "C"):
        mae = await loop.run_in_executor(None, retrain_sync, terminal)
        trained = trained or mae is not None

    if trained:
        _last_retrain_day = sim_day
    return trained
