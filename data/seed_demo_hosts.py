"""Pre-seed historical telemetry for the 3 real demo host containers.

Each container's in-process agent self-registers on startup and begins
reporting live samples — but Prophet needs days of history to forecast
meaningfully. This script generates 7 days of synthetic samples ending at
'now', so Day 1 of the demo already has:
  - 7 days of fake history per demo host
  - whatever real samples the agents add going forward

The 3 hosts are seeded with deliberate patterns:
  - demo-web-01: 'declining' (slow drift toward fill — predictive cleanup target)
  - demo-app-01: 'stable'    (well-behaved baseline)
  - demo-db-01:  'anomalous' (recent acceleration — XGBoost anomaly target)

After seeding, the user can use the UI's 'Fill disk' button to push any
host into the critical band live during the demo.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess

from data.synthetic_generator import (
    GenerationConfig,
    telemetry_for_host,
)
from shared.db import timescale_conn
from shared.logging_setup import setup_logging
from shared.schemas import Host

log = logging.getLogger(__name__)


def _docker_bin() -> str:
    """Use whichever docker is on PATH; fall back to OrbStack's bundled one."""
    which = shutil.which("docker")
    if which:
        return which
    fallback = "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"
    return fallback


def _align_container_disk(container: str, monitored_path: str, target_used_bytes: int) -> None:
    """fallocate a sparse baseline file inside the container so the live
    agent's next sample matches the seeded history's final value. Sparse
    files are instant to create regardless of size."""
    if target_used_bytes <= 0:
        return
    docker = _docker_bin()
    seed_file = f"{monitored_path}/_seed_baseline.bin"
    # Ensure the path exists first
    subprocess.run(
        [docker, "exec", container, "mkdir", "-p", monitored_path],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [docker, "exec", container, "rm", "-f", seed_file],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        [docker, "exec", container, "fallocate", "-l", str(target_used_bytes), seed_file],
        check=True,
        capture_output=True,
    )

DEMO_HOSTS: list[tuple[Host, str]] = [
    (
        Host(
            host_id="demo-web-01",
            hostname="web-prod-us-east0001",
            os="linux",
            environment="prod",
            region="us-east-1",
            role="web",
            total_disk_gb=50.0,
            monitored_path="/var/log",
        ),
        "declining",
    ),
    (
        Host(
            host_id="demo-app-01",
            hostname="app-prod-us-east0001",
            os="linux",
            environment="prod",
            region="us-east-1",
            role="app",
            total_disk_gb=100.0,
            monitored_path="/var/log/app",
        ),
        "stable",
    ),
    (
        Host(
            host_id="demo-db-01",
            hostname="db-prod-us-east0001",
            os="linux",
            environment="prod",
            region="us-east-1",
            role="db",
            total_disk_gb=500.0,
            monitored_path="/var/log/postgresql",
        ),
        "anomalous",
    ),
]


def seed(history_days: int = 7, interval_min: int = 5, seed: int = 42) -> int:
    cfg = GenerationConfig(
        host_count=len(DEMO_HOSTS),
        history_days=history_days,
        interval_min=interval_min,
        seed=seed,
    )

    import random as _random
    rng = _random.Random(seed + 100)

    host_ids = [h.host_id for h, _ in DEMO_HOSTS]

    # Clean slate: any 0% samples the live agents wrote before the seed are
    # noise vs. the synthetic history we're about to insert.
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM disk_telemetry WHERE host_id = ANY(%s)",
                (host_ids,),
            )
            log.info("cleared %d existing samples for demo hosts", cur.rowcount)
            cur.executemany(
                """
                INSERT INTO hosts (host_id, hostname, os, environment, region,
                                   role, total_disk_gb, monitored_path)
                VALUES (%(host_id)s, %(hostname)s, %(os)s, %(environment)s,
                        %(region)s, %(role)s, %(total_disk_gb)s, %(monitored_path)s)
                ON CONFLICT (host_id) DO UPDATE SET
                  hostname = EXCLUDED.hostname,
                  total_disk_gb = EXCLUDED.total_disk_gb,
                  monitored_path = EXCLUDED.monitored_path
                """,
                [h.model_dump() for h, _pat in DEMO_HOSTS],
            )
        conn.commit()
    log.info("registered %d demo hosts in DB", len(DEMO_HOSTS))

    total = 0
    for host, pattern in DEMO_HOSTS:
        samples = list(telemetry_for_host(host, pattern, cfg, rng))
        with timescale_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO disk_telemetry
                        (ts, host_id, device, total_bytes, used_bytes,
                         free_bytes, in_use_pct)
                    VALUES (%(ts)s, %(host_id)s, %(device)s, %(total_bytes)s,
                            %(used_bytes)s, %(free_bytes)s, %(in_use_pct)s)
                    ON CONFLICT DO NOTHING
                    """,
                    [s.model_dump() for s in samples],
                )
            conn.commit()
        log.info("seeded %d samples for %s (pattern=%s)", len(samples), host.host_id, pattern)

        # Align the live container's filesystem with the seeded baseline so
        # the agent's next 1-min sample doesn't lurch back to 0%.
        last = samples[-1] if samples else None
        if last is not None:
            try:
                _align_container_disk(host.host_id, host.monitored_path, last.used_bytes)
                log.info(
                    "aligned %s disk to %.2f GB baseline",
                    host.host_id, last.used_bytes / (1024**3),
                )
            except subprocess.CalledProcessError as e:
                log.warning(
                    "could not align %s container disk (is it running?): %s",
                    host.host_id, e.stderr.decode("utf-8", "ignore") if e.stderr else e,
                )

        total += len(samples)

    return total


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsgpt-seed-demo-hosts")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--interval-min", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
    n = seed(history_days=args.days, interval_min=args.interval_min, seed=args.seed)
    log.info("done: pre-seeded %d telemetry samples across %d demo hosts", n, len(DEMO_HOSTS))


if __name__ == "__main__":
    main()
