"""LLM agent CLI — invoke the LangGraph agent for a specific host or for
every host the latest ML cycle flagged as triggered."""

from __future__ import annotations

import argparse
import logging
import sys

from shared.db import timescale_conn
from shared.logging_setup import setup_logging

from .agent import run_agent

log = logging.getLogger(__name__)


def _triggered_hosts() -> list[str]:
    sql = """
        SELECT DISTINCT ON (host_id) host_id, triggered_agent
        FROM ml_predictions
        ORDER BY host_id, ts DESC
    """
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [r["host_id"] for r in rows if r["triggered_agent"]]


def main() -> int:
    parser = argparse.ArgumentParser(prog="opsgpt-agent")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--host", help="Run for one host_id")
    g.add_argument("--all-triggered", action="store_true",
                   help="Run for every host the latest ML cycle flagged")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.host:
        hosts = [args.host]
    else:
        hosts = _triggered_hosts()
        log.info("found %d triggered hosts", len(hosts))

    if not hosts:
        log.warning("nothing to do")
        return 0

    for host_id in hosts:
        log.info("=" * 60)
        log.info("AGENT RUN: %s", host_id)
        log.info("=" * 60)
        try:
            state = run_agent(host_id)
            d = state.get("decision")
            r = state.get("remediation")
            log.info(
                "  recommendation=%s  self_conf=%.2f  decision=%s (conf=%.3f)",
                state.get("llm_recommendation"),
                state.get("llm_self_confidence", 0.0),
                d.decision if d else "?",
                d.confidence_score if d else 0.0,
            )
            if r is not None:
                log.info(
                    "  remediation: %d files, %.2fGB freed",
                    r.file_count, r.bytes_freed / (1024**3),
                )
        except Exception as e:  # noqa: BLE001
            log.exception("agent run failed for %s: %s", host_id, e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
