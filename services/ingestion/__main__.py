"""Ingestion service entry point.

Two modes:
  --once       run ingest_tick once, exit
  (default)    schedule ingest_tick every INGESTION_INTERVAL_MIN minutes
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler

from shared.config import settings
from shared.logging_setup import setup_logging
from .ingest import ingest_tick

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(prog="opsgpt-ingest")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.once:
        n = ingest_tick()
        log.info("one-shot ingest complete; %d rows", n)
        return 0

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        ingest_tick,
        trigger="interval",
        minutes=settings.ingestion_interval_min,
        next_run_time=None,
        id="ingest_tick",
    )
    scheduler.start()
    # Run one immediate tick on startup
    ingest_tick()

    log.info(
        "ingestion service running every %d min; SIGINT/SIGTERM to stop",
        settings.ingestion_interval_min,
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
