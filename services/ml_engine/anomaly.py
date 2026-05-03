"""XGBoost anomaly classifier.

We train a binary classifier where positive class = "anomalous" (the synthetic
'anomalous' pattern: stable history + sharp recent acceleration) and negative
class = everything else. This reflects how the demo presents the model: the
anomaly score flags hosts whose growth is suddenly out-of-pattern, distinct
from hosts that are simply approaching a threshold steadily.

Training data is the labeled synthetic seed (see data/synthetic_generator.py).
At inference time we score live features against the saved model.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

from .features import (
    ANOMALY_FEATURE_NAMES,
    HostSeries,
    extract_anomaly_features,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("ml_artifacts/anomaly_xgb.json")


def build_training_set(
    series_list: list[HostSeries], pattern_labels: dict[str, str]
) -> tuple[pd.DataFrame, np.ndarray]:
    """Build (X, y) where y == 1 iff host's pattern is 'anomalous'."""
    rows = []
    labels = []
    for s in series_list:
        feat = extract_anomaly_features(s)
        feat["host_id"] = s.host_id
        rows.append(feat)
        labels.append(1 if pattern_labels.get(s.host_id) == "anomalous" else 0)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=list(ANOMALY_FEATURE_NAMES)), np.array([])
    X = df[list(ANOMALY_FEATURE_NAMES)].astype(float)
    y = np.asarray(labels, dtype=int)
    return X, y


def train(
    series_list: list[HostSeries],
    pattern_labels: dict[str, str],
    model_path: Path = DEFAULT_MODEL_PATH,
    test_size: float = 0.25,
    seed: int = 42,
) -> dict[str, float]:
    """Train the anomaly classifier and persist it. Returns held-out metrics."""
    X, y = build_training_set(series_list, pattern_labels)
    if X.empty or y.sum() == 0 or y.sum() == len(y):
        # Need at least one positive and one negative example to split.
        # In tiny demos this can happen — fall back to fitting on all data.
        log.warning(
            "training set has class imbalance issue (n=%d, positives=%d); "
            "fitting on all data without holdout",
            len(y), int(y.sum())
        )
        X_train, X_test, y_train, y_test = X, X, y, y
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=seed, stratify=y
        )

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    scale_pos_weight = (n_neg / n_pos) if n_pos > 0 else 1.0

    clf = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        scale_pos_weight=scale_pos_weight,
        random_state=seed,
        eval_metric="logloss",
        tree_method="hist",
    )
    clf.fit(X_train, y_train)

    train_acc = float((clf.predict(X_train) == y_train).mean())
    test_acc = float((clf.predict(X_test) == y_test).mean())
    test_pos_recall = (
        float(((clf.predict(X_test) == 1) & (y_test == 1)).sum() / max(1, y_test.sum()))
        if y_test.sum() > 0
        else float("nan")
    )

    model_path.parent.mkdir(parents=True, exist_ok=True)
    clf.save_model(str(model_path))
    log.info(
        "trained XGBoost anomaly classifier: train_acc=%.3f test_acc=%.3f "
        "anomaly_recall=%.3f n_train=%d n_pos=%d -> %s",
        train_acc, test_acc, test_pos_recall, len(y_train), n_pos, model_path,
    )
    return {
        "train_acc": train_acc,
        "test_acc": test_acc,
        "anomaly_recall": test_pos_recall,
        "n_train": float(len(y_train)),
        "n_pos": float(n_pos),
    }


def load(model_path: Path = DEFAULT_MODEL_PATH) -> xgb.XGBClassifier:
    if not model_path.exists():
        raise FileNotFoundError(
            f"no XGBoost model at {model_path}; run "
            "`opsgpt-ml-train` first to fit on the synthetic dataset"
        )
    clf = xgb.XGBClassifier()
    clf.load_model(str(model_path))
    return clf


def score(clf: xgb.XGBClassifier, series: HostSeries) -> float:
    """Score one host: returns probability of anomaly class (0..1)."""
    feat = extract_anomaly_features(series)
    X = pd.DataFrame([feat], columns=list(ANOMALY_FEATURE_NAMES)).astype(float)
    proba = clf.predict_proba(X)[0]
    # XGBClassifier exposes classes_ in order — pull the prob for class 1.
    classes = list(clf.classes_)
    if 1 in classes:
        return float(proba[classes.index(1)])
    return 0.0


def score_batch(clf: xgb.XGBClassifier, series_list: list[HostSeries]) -> dict[str, float]:
    """Score many hosts at once. Returns {host_id: anomaly_score}."""
    if not series_list:
        return {}
    rows = []
    host_ids = []
    for s in series_list:
        rows.append(extract_anomaly_features(s))
        host_ids.append(s.host_id)
    X = pd.DataFrame(rows, columns=list(ANOMALY_FEATURE_NAMES)).astype(float)
    proba = clf.predict_proba(X)
    classes = list(clf.classes_)
    pos_idx = classes.index(1) if 1 in classes else 0
    return {host_id: float(proba[i, pos_idx]) for i, host_id in enumerate(host_ids)}
