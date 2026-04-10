"""Anomaly detection engine using Isolation Forest.

Collects per-minute metric vectors from operational state, trains an
IsolationForest on normal behaviour, and scores current observations
to detect operational anomalies.

P5-3-1: Isolation forest baseline
P5-3-2: Prometheus metrics integration
P5-3-3: Root cause trace
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from services.state import OperationalState

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

BUFFER_MAX = 2000  # ~33 hours of sim time
MIN_SAMPLES_FOR_TRAINING = 120  # 2 hours of data
RETRAIN_INTERVAL_TICKS = 60  # retrain every 60 sim-minutes
ANOMALY_THRESHOLD_AMBER = -0.1  # decision_function score
ANOMALY_THRESHOLD_RED = -0.3

# Feature names for interpretability
FEATURE_NAMES = [
    "security_queue_A",
    "security_queue_B",
    "security_queue_C",
    "security_wait_A",
    "security_wait_B",
    "security_wait_C",
    "baggage_util_avg",
    "delay_minutes_total",
    "delayed_flight_count",
    "active_incident_count",
    "vehicle_util_avg",
    "runway_capacity_pct",
    "weather_category",
    "active_bottleneck_count",
]


# ── Data structures ──────────────────────────────────────────


@dataclass
class AnomalyResult:
    """Result of anomaly scoring for the current tick."""
    score: float  # raw decision_function output (negative = anomaly)
    normalized_score: float  # 0–1 scale (0 = most anomalous)
    status: str  # "normal" | "amber" | "red"
    z_scores: dict[str, float] = field(default_factory=dict)
    root_cause: str | None = None
    root_cause_feature: str | None = None
    detected_at: datetime | None = None


@dataclass
class EventRecord:
    """A cached event for root cause analysis."""
    event_type: str
    timestamp: datetime
    summary: str


# ── Anomaly Detector ─────────────────────────────────────────

WEATHER_ORDINAL = {"CAVOK": 0, "VMC": 1, "IMC": 2, "LIFR": 3}


class AnomalyDetector:
    """Isolation-forest-based anomaly detection over operational metrics."""

    def __init__(self) -> None:
        self._buffer: deque[np.ndarray] = deque(maxlen=BUFFER_MAX)
        self._model = None  # IsolationForest instance
        self._trained = False
        self._ticks_since_train = 0
        self._latest_result: AnomalyResult | None = None

        # Running statistics for z-score computation
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None

        # Event history for root cause analysis (P5-3-3)
        self._event_history: deque[EventRecord] = deque(maxlen=1800)  # 30 min
        self._anomaly_onset: datetime | None = None

    def extract_features(
        self,
        state: OperationalState,
        active_bottleneck_count: int = 0,
    ) -> np.ndarray:
        """Extract a feature vector from current operational state."""
        terminals = ["Terminal A", "Terminal B", "Terminal C"]

        security_queues = [
            float(state.security.get(t, type("", (), {"queue_depth": 0})).queue_depth)
            for t in terminals
        ]
        security_waits = [
            float(state.security.get(t, type("", (), {"forecast_wait_minutes": 0.0})).forecast_wait_minutes)
            for t in terminals
        ]

        # Baggage utilisation average
        baggage_utils = [z.utilisation_pct for z in state.baggage_zones.values()]
        baggage_util_avg = float(np.mean(baggage_utils)) if baggage_utils else 0.0

        # Delay totals
        active_flights = [
            f for f in state.flights.values()
            if f.status not in ("completed", "cancelled")
        ]
        delay_total = sum(f.delay_minutes for f in active_flights)
        delayed_count = sum(1 for f in active_flights if f.delay_minutes > 0)

        # Vehicle utilisation
        vehicle_utils = [v.utilisation_pct for v in state.vehicles.values()]
        vehicle_util_avg = float(np.mean(vehicle_utils)) if vehicle_utils else 0.0

        # Weather
        weather_cat = WEATHER_ORDINAL.get(state.weather.category, 0)

        features = np.array(
            security_queues
            + security_waits
            + [
                baggage_util_avg,
                delay_total,
                float(delayed_count),
                float(len(state.active_incidents)),
                vehicle_util_avg,
                state.weather.runway_capacity_pct,
                float(weather_cat),
                float(active_bottleneck_count),
            ],
            dtype=np.float64,
        )
        return features

    def record_event(
        self, event_type: str, timestamp: datetime, summary: str,
    ) -> None:
        """Cache a recent event for root cause tracing (P5-3-3)."""
        self._event_history.append(
            EventRecord(event_type=event_type, timestamp=timestamp, summary=summary)
        )

    def on_tick(
        self,
        state: OperationalState,
        active_bottleneck_count: int = 0,
    ) -> AnomalyResult | None:
        """Called each sim-minute. Collects features, retrains, and scores."""
        features = self.extract_features(state, active_bottleneck_count)
        self._buffer.append(features)
        self._ticks_since_train += 1

        # Retrain periodically
        if (
            self._ticks_since_train >= RETRAIN_INTERVAL_TICKS
            and len(self._buffer) >= MIN_SAMPLES_FOR_TRAINING
        ):
            self._retrain()
            self._ticks_since_train = 0

        # Score if model available
        if not self._trained or self._model is None:
            return None

        return self._score(features, state.sim_time)

    def _retrain(self) -> None:
        """Retrain the isolation forest on the current buffer."""
        from sklearn.ensemble import IsolationForest

        data = np.array(list(self._buffer))

        self._model = IsolationForest(
            n_estimators=100,
            contamination=0.05,
            random_state=42,
            n_jobs=1,
        )
        self._model.fit(data)
        self._trained = True

        # Compute running stats for z-score
        self._mean = data.mean(axis=0)
        self._std = data.std(axis=0)
        # Avoid division by zero
        self._std[self._std < 1e-8] = 1.0

        logger.info(
            "Anomaly model retrained on %d samples", len(data),
        )

    def _score(
        self, features: np.ndarray, sim_time: datetime | None,
    ) -> AnomalyResult:
        """Score a single observation."""
        raw_score = float(self._model.decision_function(features.reshape(1, -1))[0])

        # Normalize to 0–1 (higher = more normal)
        # decision_function returns positive for inliers, negative for outliers
        # Typical range: [-0.5, 0.5] — clamp and shift
        normalized = float(np.clip((raw_score + 0.5) / 1.0, 0.0, 1.0))

        # Determine status
        if raw_score < ANOMALY_THRESHOLD_RED:
            status = "red"
        elif raw_score < ANOMALY_THRESHOLD_AMBER:
            status = "amber"
        else:
            status = "normal"

        # Compute per-feature z-scores
        z_scores: dict[str, float] = {}
        if self._mean is not None and self._std is not None:
            z_vals = (features - self._mean) / self._std
            for i, name in enumerate(FEATURE_NAMES):
                z_scores[name] = round(float(z_vals[i]), 3)

        # Root cause analysis (P5-3-3)
        root_cause = None
        root_cause_feature = None
        if status != "normal":
            root_cause_feature, root_cause = self._trace_root_cause(
                z_scores, sim_time,
            )
            if self._anomaly_onset is None:
                self._anomaly_onset = sim_time
        else:
            self._anomaly_onset = None

        result = AnomalyResult(
            score=round(raw_score, 4),
            normalized_score=round(normalized, 4),
            status=status,
            z_scores=z_scores,
            root_cause=root_cause,
            root_cause_feature=root_cause_feature,
            detected_at=self._anomaly_onset,
        )
        self._latest_result = result
        return result

    def _trace_root_cause(
        self,
        z_scores: dict[str, float],
        sim_time: datetime | None,
    ) -> tuple[str | None, str | None]:
        """P5-3-3: Identify the most likely root cause of the anomaly.

        Strategy: find the feature with the highest absolute z-score,
        then search recent events for the most related event type.
        """
        if not z_scores:
            return None, None

        # Find feature with highest absolute deviation
        worst_feature = max(z_scores.items(), key=lambda kv: abs(kv[1]))
        feature_name = worst_feature[0]
        feature_z = worst_feature[1]

        # Map features to likely event types
        feature_event_map: dict[str, list[str]] = {
            "security_queue_A": ["SecurityCongestionDetected", "PassengerStatusChanged"],
            "security_queue_B": ["SecurityCongestionDetected", "PassengerStatusChanged"],
            "security_queue_C": ["SecurityCongestionDetected", "PassengerStatusChanged"],
            "security_wait_A": ["SecurityCongestionDetected"],
            "security_wait_B": ["SecurityCongestionDetected"],
            "security_wait_C": ["SecurityCongestionDetected"],
            "baggage_util_avg": ["BaggageStatusChanged"],
            "delay_minutes_total": ["FlightStatusChanged", "FlightCTOTAssigned"],
            "delayed_flight_count": ["FlightStatusChanged"],
            "active_incident_count": ["IncidentCreated"],
            "vehicle_util_avg": ["GroundVehicleDispatched", "GroundVehicleReturned"],
            "runway_capacity_pct": ["WeatherStateChanged", "IncidentCreated"],
            "weather_category": ["WeatherStateChanged"],
            "active_bottleneck_count": ["BottleneckDetected"],
        }

        related_events = feature_event_map.get(feature_name, [])

        # Search recent event history for the first related event
        root_event = None
        if sim_time and related_events:
            for evt in reversed(list(self._event_history)):
                if evt.event_type in related_events:
                    root_event = evt
                    break

        direction = "above" if feature_z > 0 else "below"
        cause = (
            f"{feature_name} is {abs(feature_z):.1f}σ {direction} normal"
        )
        if root_event:
            cause += f" — likely triggered by {root_event.event_type}"
            cause += f" ({root_event.summary})"

        return feature_name, cause

    def get_latest_result(self) -> AnomalyResult | None:
        return self._latest_result

    def get_status(self) -> dict:
        """Return detector status for API consumers."""
        result = self._latest_result
        return {
            "trained": self._trained,
            "buffer_size": len(self._buffer),
            "min_samples": MIN_SAMPLES_FOR_TRAINING,
            "retrain_interval": RETRAIN_INTERVAL_TICKS,
            "anomalies": (
                {
                    "score": result.score,
                    "normalized_score": result.normalized_score,
                    "status": result.status,
                    "z_scores": result.z_scores,
                    "root_cause": result.root_cause,
                    "root_cause_feature": result.root_cause_feature,
                    "detected_at": (
                        result.detected_at.isoformat()
                        if result.detected_at
                        else None
                    ),
                }
                if result
                else None
            ),
        }


# ── Module-level singleton ───────────────────────────────────

detector = AnomalyDetector()
