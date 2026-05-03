"""ML Engine CLI.

Three modes:
  --train      Fit the XGBoost anomaly classifier against the synthetic seed.
               Run once after generating data; persists the model under
               ml_artifacts/ for downstream `--once` runs.
  --once       Run one full Prophet+XGBoost cycle over every host.
  (default)    Scheduled mode: run --once every ML_RUN_INTERVAL_MIN minutes.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler

import pandas as pd

from data.synthetic_generator import (
    GenerationConfig,
    assign_patterns,
    generate_all,
)
from shared.config import settings
from shared.logging_setup import setup_logging

from .anomaly import DEFAULT_MODEL_PATH, train as train_anomaly
from .features import HostSeries
from .pipeline import run_full_cycle

log = logging.getLogger(__name__)


def _train(host_count: int = 500) -> None:
    """Train the XGBoost anomaly classifier on a large ephemeral synthetic
    dataset (in-memory, separate from the demo's TimescaleDB fleet).

    The 50-host demo fleet has too few anomalies to give a stable holdout
    estimate. Training on 500 stratified synthetic hosts produces a robust
    model whose generalization is honest to evaluate, then we use it to
    score whatever live fleet exists in the DB.
    """
    cfg = GenerationConfig(
        host_count=host_count,
        history_days=settings.synthetic_history_days,
        interval_min=settings.synthetic_telemetry_interval_min,
        seed=42,
    )
    log.info(
        "generating %d ephemeral training hosts (in-memory; no DB writes)",
        host_count,
    )
    hosts, pattern_labels, telemetry = generate_all(cfg)

    # Bucket the streamed telemetry into per-host pandas frames for the same
    # HostSeries shape the live pipeline produces.
    by_host: dict[str, list[tuple]] = {}
    for sample in telemetry:
        by_host.setdefault(sample.host_id, []).append(
            (sample.ts, sample.in_use_pct)
        )

    series_list: list[HostSeries] = []
    for host in hosts:
        rows = by_host.get(host.host_id, [])
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["ds", "y"])
        df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_convert(None)
        df = df.sort_values("ds").reset_index(drop=True)
        series_list.append(
            HostSeries(host_id=host.host_id, device=host.monitored_path, df=df)
        )

    log.info("built %d host series for training", len(series_list))
    metrics = train_anomaly(series_list, pattern_labels, model_path=DEFAULT_MODEL_PATH)
    log.info("training metrics: %s", metrics)


def main() -> int:
    parser = argparse.ArgumentParser(prog="opsgpt-ml")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--train", action="store_true", help="Fit XGBoost on synthetic labels.")
    g.add_argument("--once", action="store_true", help="Run one ML cycle and exit.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.train:
        _train()
        return 0

    if args.once:
        result = run_full_cycle()
        log.info("one-shot ML complete: %s", result)
        return 0

    # Scheduled mode
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_full_cycle,
        trigger="interval",
        minutes=settings.ml_run_interval_min,
        id="ml_cycle",
    )
    scheduler.start()
    run_full_cycle()  # immediate first run

    log.info(
        "ML engine running every %d min; SIGINT/SIGTERM to stop",
        settings.ml_run_interval_min,
    )

    stopping = False

    def _signal_handler(signum, _frame):  # noqa: ARG001
        nonlocal stopping
        log.info("received signal %d; shutting down", signum)
        stopping = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    while not stopping:
        time.sleep(1)
    scheduler.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
