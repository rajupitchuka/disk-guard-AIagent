"""Feature-engineering unit tests. Operate on Pydantic / pandas objects only —
no DB or model required."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.ml_engine.features import (
    ANOMALY_FEATURE_NAMES,
    HostSeries,
    extract_anomaly_features,
)


def _series(values: list[float], host_id: str = "h0", interval_min: int = 5) -> HostSeries:
    n = len(values)
    ds = pd.date_range(start="2026-04-01", periods=n, freq=f"{interval_min}min")
    df = pd.DataFrame({"ds": ds, "y": values})
    return HostSeries(host_id=host_id, device="/", df=df)


def test_features_have_expected_keys() -> None:
    s = _series([50.0] * 100)
    feat = extract_anomaly_features(s)
    assert set(feat.keys()) == set(ANOMALY_FEATURE_NAMES)


def test_stable_series_low_slopes() -> None:
    rng = np.random.default_rng(0)
    values = (50.0 + rng.normal(0, 0.3, 200)).tolist()
    feat = extract_anomaly_features(_series(values))
    assert abs(feat["slope_full"]) < 0.05
    assert abs(feat["slope_acceleration"]) < 0.5


def test_declining_series_positive_slope() -> None:
    # 200 samples, +0.05/h drift over ~16h
    values = [50.0 + 0.05 * (i / 12) for i in range(200)]  # 5min cadence -> /12 per hour
    feat = extract_anomaly_features(_series(values))
    assert feat["slope_full"] > 0
    assert feat["slope_full"] < 1.0  # not anomalous


def test_anomalous_series_high_acceleration() -> None:
    # 7 days at 5-min cadence so the "recent 24h" window is distinct from the
    # full series. 80% stable, last 20% accelerating.
    n = 7 * 24 * 12
    knee = int(n * 0.8)
    values = [50.0] * knee + [50.0 + 0.05 * (i + 1) for i in range(n - knee)]
    feat = extract_anomaly_features(_series(values))
    assert feat["slope_recent_24h"] > feat["slope_full"], (
        "recent slope should exceed full-window slope on anomaly"
    )
    assert feat["slope_acceleration"] > 0.5


def test_critical_series_high_mean() -> None:
    values = [92.0 + (i % 3) * 0.1 for i in range(200)]
    feat = extract_anomaly_features(_series(values))
    assert feat["mean"] > 90.0
    assert feat["current_value"] > 90.0


def test_empty_series_returns_zeros() -> None:
    s = HostSeries(host_id="h0", device="/", df=pd.DataFrame(columns=["ds", "y"]))
    feat = extract_anomaly_features(s)
    assert all(v == 0.0 for v in feat.values())
