"""Synthetic Datadog telemetry generator.

Produces a realistic 3000-host fleet with a mix of disk-usage patterns. The
ML engine, agent, and demo UI are all driven by what this module emits, so
the patterns matter — they need to give the demo something interesting to
predict, classify, and reason about.

Pattern mix (default; override via CLI):

  - 70%  STABLE    — usage holds steady around a baseline with mild diurnal
                      drift. ML should forecast no breach. Decision: noop.
  - 15%  DECLINING — slow steady decline at 0.5-2 GB/day. Prophet should
                      predict the threshold crossing within the 7-day window.
                      Decision: agent should preemptively clean.
  - 10%  ANOMALOUS — stable then abrupt acceleration in last 6-24h (e.g. a
                      runaway logger). XGBoost should flag this; LLM agent
                      should escalate rather than clean.
  - 5%   CRITICAL  — already > 90% used. ML triggers immediately, agent
                      runs reactive cleanup.

The OS / role / region / environment mix is balanced for visual variety in
the fleet view.
"""

from __future__ import annotations

import argparse
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from shared.config import settings
from shared.logging_setup import setup_logging
from shared.schemas import DiskTelemetry, Host

log = logging.getLogger(__name__)

GB = 1024**3

OSES = ["windows", "linux"]
OS_WEIGHTS = [0.55, 0.45]  # roughly the TCS infra mix

ENVIRONMENTS = ["prod", "staging", "dev"]
ENV_WEIGHTS = [0.60, 0.25, 0.15]

REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1", "ap-southeast-1"]

ROLES = ["web", "app", "db", "batch", "cache", "queue", "ml-worker", "build-agent"]

# Default pattern probabilities — must sum to 1.0
PATTERN_MIX = {
    "stable": 0.70,
    "declining": 0.15,
    "anomalous": 0.10,
    "critical": 0.05,
}


@dataclass
class GenerationConfig:
    host_count: int
    history_days: int
    interval_min: int
    seed: int = 42
    pattern_mix: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pattern_mix is None:
            self.pattern_mix = PATTERN_MIX
        s = sum(self.pattern_mix.values())
        if abs(s - 1.0) > 0.001:
            raise ValueError(f"pattern_mix must sum to 1.0, got {s}")


def make_hosts(cfg: GenerationConfig) -> list[Host]:
    rng = random.Random(cfg.seed)
    hosts: list[Host] = []
    for i in range(cfg.host_count):
        os = rng.choices(OSES, weights=OS_WEIGHTS, k=1)[0]
        env = rng.choices(ENVIRONMENTS, weights=ENV_WEIGHTS, k=1)[0]
        region = rng.choice(REGIONS)
        role = rng.choice(ROLES)
        # Disk size depends on role
        if role == "db":
            total_gb = rng.choice([500.0, 1000.0, 2000.0])
        elif role in ("ml-worker", "batch"):
            total_gb = rng.choice([250.0, 500.0, 1000.0])
        else:
            total_gb = rng.choice([100.0, 250.0, 500.0])
        host_id = f"host-{i:05d}"
        hostname = f"{role}-{env}-{region.split('-')[0]}{i:04d}"
        path = "C:\\" if os == "windows" else "/"
        hosts.append(
            Host(
                host_id=host_id,
                hostname=hostname,
                os=os,
                environment=env,
                region=region,
                role=role,
                total_disk_gb=total_gb,
                monitored_path=path,
            )
        )
    return hosts


def assign_patterns(hosts: list[Host], cfg: GenerationConfig) -> dict[str, str]:
    """Deterministic stratified pattern assignment.

    Random sampling produces wrong proportions at small N — at 50 hosts with a
    5% critical rate, random sampling routinely yields zero critical hosts.
    The demo must show every pattern, so we allocate exact counts (with
    rounding correction) then shuffle deterministically.
    """
    rng = random.Random(cfg.seed + 1)
    patterns = list(cfg.pattern_mix.keys())
    n = len(hosts)

    counts = {p: int(cfg.pattern_mix[p] * n) for p in patterns}
    # Rounding correction: ensure at least 1 of each pattern (so demos always
    # have one to point at), then top up the largest bucket to hit exactly n.
    for p in patterns:
        if counts[p] == 0 and cfg.pattern_mix[p] > 0:
            counts[p] = 1
    delta = n - sum(counts.values())
    if delta != 0:
        # Adjust the most-common pattern to absorb rounding remainder
        biggest = max(patterns, key=lambda p: cfg.pattern_mix[p])
        counts[biggest] += delta

    bag: list[str] = []
    for p in patterns:
        bag.extend([p] * counts[p])
    rng.shuffle(bag)
    return {h.host_id: bag[i] for i, h in enumerate(hosts)}


def _diurnal_factor(ts: datetime) -> float:
    """Mild day-night usage cycle: ~+2% during business hours."""
    hour = ts.hour
    if 9 <= hour <= 18:
        return 1.02
    return 1.0


def _generate_pattern_curve(
    pattern: str,
    n_samples: int,
    start_pct: float,
    rng: random.Random,
) -> list[float]:
    """Return n_samples in_use_pct values for the given pattern.

    All curves are clipped to [0, 99.9] to stay physically valid.
    """
    pct = start_pct
    series: list[float] = []

    if pattern == "stable":
        # Baseline + small noise + diurnal handled outside
        baseline = pct
        for _ in range(n_samples):
            sample = baseline + rng.gauss(0, 0.3)
            series.append(max(0.0, min(99.9, sample)))

    elif pattern == "declining":
        # Slow steady drift upward (i.e. used % goes up, free % goes down)
        # Rate: 0.5–2 GB/day expressed as % depends on disk size; here we
        # choose a per-sample increment that yields ~5–15% rise over
        # history_days at the given sample rate.
        rate = rng.uniform(0.0008, 0.0025)  # %/sample
        for i in range(n_samples):
            sample = pct + rate * i + rng.gauss(0, 0.2)
            series.append(max(0.0, min(99.9, sample)))

    elif pattern == "anomalous":
        # Stable for first 80% of the window, then sharp acceleration
        knee = int(n_samples * 0.8)
        baseline = pct
        for i in range(n_samples):
            if i < knee:
                sample = baseline + rng.gauss(0, 0.3)
            else:
                # Accelerate hard: 20-40% jump over the last 20% of samples
                progress = (i - knee) / max(1, n_samples - knee)
                jump = rng.uniform(20, 40) * progress
                sample = baseline + jump + rng.gauss(0, 0.5)
            series.append(max(0.0, min(99.9, sample)))

    elif pattern == "critical":
        # Already very high; oscillate near 90-95%
        baseline = max(pct, 90.0)
        for i in range(n_samples):
            sample = baseline + rng.gauss(0, 0.4) + i * 0.005
            series.append(max(0.0, min(99.9, sample)))

    else:
        raise ValueError(f"unknown pattern: {pattern}")

    return series


def telemetry_for_host(
    host: Host,
    pattern: str,
    cfg: GenerationConfig,
    rng: random.Random,
) -> Iterator[DiskTelemetry]:
    n_samples = (cfg.history_days * 24 * 60) // cfg.interval_min
    end_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(minutes=cfg.interval_min * (n_samples - 1))

    # Pick a starting in_use_pct based on pattern
    start_pct = {
        "stable": rng.uniform(20, 60),
        "declining": rng.uniform(40, 70),
        "anomalous": rng.uniform(35, 55),
        "critical": rng.uniform(88, 93),
    }[pattern]

    pcts = _generate_pattern_curve(pattern, n_samples, start_pct, rng)
    total_bytes = int(host.total_disk_gb * GB)
    device = host.monitored_path

    for i, pct in enumerate(pcts):
        ts = start_ts + timedelta(minutes=cfg.interval_min * i)
        pct_with_diurnal = min(99.9, pct * _diurnal_factor(ts))
        used_bytes = int(total_bytes * (pct_with_diurnal / 100.0))
        free_bytes = total_bytes - used_bytes
        yield DiskTelemetry(
            ts=ts,
            host_id=host.host_id,
            device=device,
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            free_bytes=free_bytes,
            in_use_pct=round(pct_with_diurnal, 3),
        )


def generate_all(cfg: GenerationConfig) -> tuple[list[Host], dict[str, str], Iterator[DiskTelemetry]]:
    """Top-level entry: returns (hosts, pattern_map, telemetry_iterator).

    The telemetry iterator is lazy — for 3000 hosts × 7 days × 5-min cadence
    we produce ~6M rows. Stream them into the DB rather than buffering.
    """
    hosts = make_hosts(cfg)
    patterns = assign_patterns(hosts, cfg)
    rng = random.Random(cfg.seed + 2)

    def telemetry_iter() -> Iterator[DiskTelemetry]:
        for host in hosts:
            yield from telemetry_for_host(host, patterns[host.host_id], cfg, rng)

    return hosts, patterns, telemetry_iter()


def pattern_summary(patterns: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in patterns.values():
        counts[p] = counts.get(p, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# CLI: write directly to TimescaleDB (used for the seed step)
# ---------------------------------------------------------------------------

def _write_to_db(hosts: list[Host], telemetry: Iterator[DiskTelemetry], batch_size: int = 5000) -> int:
    """Insert hosts then stream telemetry. Returns total telemetry rows written."""
    from shared.db import timescale_conn

    log.info("writing %d hosts to TimescaleDB", len(hosts))
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO hosts (host_id, hostname, os, environment, region, role, total_disk_gb, monitored_path)
                VALUES (%(host_id)s, %(hostname)s, %(os)s, %(environment)s, %(region)s, %(role)s, %(total_disk_gb)s, %(monitored_path)s)
                ON CONFLICT (host_id) DO UPDATE SET
                  hostname = EXCLUDED.hostname,
                  os = EXCLUDED.os,
                  environment = EXCLUDED.environment,
                  region = EXCLUDED.region,
                  role = EXCLUDED.role,
                  total_disk_gb = EXCLUDED.total_disk_gb,
                  monitored_path = EXCLUDED.monitored_path
                """,
                [h.model_dump() for h in hosts],
            )
        conn.commit()

    log.info("streaming telemetry...")
    total = 0
    batch: list[dict] = []
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            for sample in telemetry:
                batch.append(sample.model_dump())
                if len(batch) >= batch_size:
                    cur.executemany(
                        """
                        INSERT INTO disk_telemetry
                            (ts, host_id, device, total_bytes, used_bytes, free_bytes, in_use_pct)
                        VALUES
                            (%(ts)s, %(host_id)s, %(device)s, %(total_bytes)s, %(used_bytes)s, %(free_bytes)s, %(in_use_pct)s)
                        ON CONFLICT DO NOTHING
                        """,
                        batch,
                    )
                    total += len(batch)
                    batch.clear()
                    if total % 50000 == 0:
                        log.info("  wrote %d rows", total)
            if batch:
                cur.executemany(
                    """
                    INSERT INTO disk_telemetry
                        (ts, host_id, device, total_bytes, used_bytes, free_bytes, in_use_pct)
                    VALUES
                        (%(ts)s, %(host_id)s, %(device)s, %(total_bytes)s, %(used_bytes)s, %(free_bytes)s, %(in_use_pct)s)
                    ON CONFLICT DO NOTHING
                    """,
                    batch,
                )
                total += len(batch)
        conn.commit()
    log.info("wrote %d telemetry rows total", total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsgpt-generate-data")
    parser.add_argument("--hosts", type=int, default=settings.synthetic_host_count)
    parser.add_argument("--days", type=int, default=settings.synthetic_history_days)
    parser.add_argument("--interval-min", type=int, default=settings.synthetic_telemetry_interval_min)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary and a few samples; don't write to DB.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    cfg = GenerationConfig(
        host_count=args.hosts,
        history_days=args.days,
        interval_min=args.interval_min,
        seed=args.seed,
    )
    log.info(
        "generating %d hosts × %d days × %d-min cadence",
        cfg.host_count, cfg.history_days, cfg.interval_min,
    )

    hosts, patterns, telemetry = generate_all(cfg)
    summary = pattern_summary(patterns)
    log.info("pattern mix: %s", summary)

    if args.dry_run:
        log.info("dry-run: showing first 5 hosts and 3 telemetry samples each")
        sampler = telemetry  # already iterator
        seen_per_host: dict[str, int] = {}
        emitted = 0
        for sample in sampler:
            if seen_per_host.get(sample.host_id, 0) >= 3:
                continue
            seen_per_host[sample.host_id] = seen_per_host.get(sample.host_id, 0) + 1
            log.info("  %s | %s | pct=%.2f | pattern=%s",
                     sample.ts.isoformat(), sample.host_id, sample.in_use_pct,
                     patterns[sample.host_id])
            emitted += 1
            if emitted >= 15:
                break
        return

    rows = _write_to_db(hosts, telemetry)
    log.info("done: %d hosts, %d telemetry rows", len(hosts), rows)


if __name__ == "__main__":
    main()
