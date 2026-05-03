"""End-to-end tests for the XGBoost anomaly path on small synthetic data —
no DB or pretrained model required."""

from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from services.ml_engine.anomaly import (
    build_training_set,
    score_batch,
    train,
)
from services.ml_engine.features import HostSeries


def _make_synthetic_series(pattern: str, host_id: str, seed: int) -> HostSeries:
    """Reproduce the four pattern shapes locally so we don't need TimescaleDB."""
    rng = random.Random(seed)
    n = 7 * 24 * 12  # 7 days at 5-min cadence
    if pattern == "stable":
        values = [50.0 + rng.gauss(0, 0.3) for _ in range(n)]
    elif pattern == "declining":
        values = [40.0 + 0.001 * i + rng.gauss(0, 0.2) for i in range(n)]
    elif pattern == "anomalous":
        knee = int(n * 0.8)
        values = []
        for i in range(n):
            if i < knee:
                values.append(45.0 + rng.gauss(0, 0.3))
            else:
                progress = (i - knee) / max(1, n - knee)
                values.append(45.0 + 30.0 * progress + rng.gauss(0, 0.3))
    elif pattern == "critical":
        values = [92.0 + rng.gauss(0, 0.4) + i * 0.001 for i in range(n)]
    else:
        raise ValueError(pattern)

    ds = pd.date_range(start="2026-04-01", periods=n, freq="5min")
    df = pd.DataFrame({"ds": ds, "y": np.clip(values, 0, 99.9)})
    return HostSeries(host_id=host_id, device="/", df=df)


@pytest.fixture
def labeled_series() -> tuple[list[HostSeries], dict[str, str]]:
    series_list: list[HostSeries] = []
    labels: dict[str, str] = {}
    seed = 0
    # 30 stable, 10 declining, 10 anomalous, 5 critical — enough imbalance
    # for XGBoost to learn.
    for pat, n in [("stable", 30), ("declining", 10), ("anomalous", 10), ("critical", 5)]:
        for i in range(n):
            host_id = f"{pat}-{i:02d}"
            series_list.append(_make_synthetic_series(pat, host_id, seed))
            labels[host_id] = pat
            seed += 1
    return series_list, labels


def test_build_training_set_labels_correctly(labeled_series) -> None:
    series_list, labels = labeled_series
    X, y = build_training_set(series_list, labels)
    assert len(X) == len(series_list)
    assert int(y.sum()) == 10  # 10 anomalous hosts
    # Feature columns present
    assert "slope_acceleration" in X.columns
    assert "current_value" in X.columns


def test_train_recovers_anomalies(labeled_series, tmp_path) -> None:
    series_list, labels = labeled_series
    model_path = tmp_path / "anomaly_xgb.json"
    metrics = train(series_list, labels, model_path=model_path, seed=42)
    assert model_path.exists()
    # On this clean synthetic data, accuracy should be near-perfect
    assert metrics["test_acc"] >= 0.85
    assert metrics["anomaly_recall"] >= 0.5  # at least catches half of anomalies


def test_score_batch_assigns_high_score_to_anomalies(labeled_series, tmp_path) -> None:
    series_list, labels = labeled_series
    model_path = tmp_path / "anomaly_xgb.json"
    train(series_list, labels, model_path=model_path, seed=42)

    import xgboost as xgb
    clf = xgb.XGBClassifier()
    clf.load_model(str(model_path))

    scores = score_batch(clf, series_list)
    anomalous_scores = [scores[s.host_id] for s in series_list if labels[s.host_id] == "anomalous"]
    stable_scores = [scores[s.host_id] for s in series_list if labels[s.host_id] == "stable"]
    assert max(anomalous_scores) > 0.5
    assert max(stable_scores) < max(anomalous_scores)
