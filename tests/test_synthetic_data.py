"""Tests for the synthetic data generator. Runs without Docker — operates
purely on Pydantic objects."""

from __future__ import annotations

import itertools
from collections import Counter

import pytest

from data.synthetic_generator import (
    GenerationConfig,
    assign_patterns,
    generate_all,
    make_hosts,
    pattern_summary,
    telemetry_for_host,
)
from shared.schemas import DiskTelemetry, Host


@pytest.fixture
def small_cfg() -> GenerationConfig:
    return GenerationConfig(host_count=100, history_days=2, interval_min=15, seed=42)


def test_make_hosts_count_and_uniqueness(small_cfg: GenerationConfig) -> None:
    hosts = make_hosts(small_cfg)
    assert len(hosts) == 100
    assert len({h.host_id for h in hosts}) == 100
    assert all(h.os in ("windows", "linux") for h in hosts)
    assert all(h.environment in ("prod", "staging", "dev") for h in hosts)


def test_pattern_assignment_deterministic(small_cfg: GenerationConfig) -> None:
    hosts = make_hosts(small_cfg)
    p1 = assign_patterns(hosts, small_cfg)
    p2 = assign_patterns(hosts, small_cfg)
    assert p1 == p2  # same seed → same assignment


def test_pattern_mix_roughly_matches_target(small_cfg: GenerationConfig) -> None:
    # 1000 hosts gives a tighter distribution
    cfg = GenerationConfig(host_count=1000, history_days=1, interval_min=15, seed=42)
    hosts = make_hosts(cfg)
    patterns = assign_patterns(hosts, cfg)
    summary = pattern_summary(patterns)
    # Each bucket should be within ~5% of the target proportion
    assert abs(summary.get("stable", 0) / 1000 - 0.70) < 0.05
    assert abs(summary.get("declining", 0) / 1000 - 0.15) < 0.05
    assert abs(summary.get("anomalous", 0) / 1000 - 0.10) < 0.05
    assert abs(summary.get("critical", 0) / 1000 - 0.05) < 0.05


def test_critical_pattern_starts_high(small_cfg: GenerationConfig) -> None:
    """The 'critical' pattern must produce in_use_pct values that already
    exceed 85% — these are the hosts that should immediately trigger
    reactive cleanup."""
    import random

    rng = random.Random(0)
    host = Host(
        host_id="h0", hostname="h0", os="linux", environment="prod",
        region="us-east-1", role="db", total_disk_gb=500, monitored_path="/",
    )
    samples = list(telemetry_for_host(host, "critical", small_cfg, rng))
    pcts = [s.in_use_pct for s in samples]
    assert min(pcts) > 85, f"critical pattern produced low pct: min={min(pcts):.1f}"


def test_anomalous_pattern_has_late_acceleration(small_cfg: GenerationConfig) -> None:
    """Anomalous hosts should be relatively flat for ~80% of the window
    then sharply accelerate — that's what makes them anomalous to XGBoost."""
    import random

    rng = random.Random(0)
    host = Host(
        host_id="h0", hostname="h0", os="linux", environment="prod",
        region="us-east-1", role="db", total_disk_gb=500, monitored_path="/",
    )
    cfg = GenerationConfig(host_count=1, history_days=7, interval_min=15, seed=42)
    samples = list(telemetry_for_host(host, "anomalous", cfg, rng))
    knee = int(len(samples) * 0.8)
    early = [s.in_use_pct for s in samples[:knee]]
    late = [s.in_use_pct for s in samples[knee:]]
    assert max(late) > max(early) + 10, "anomalous pattern lacks late acceleration"


def test_telemetry_invariants(small_cfg: GenerationConfig) -> None:
    """Every emitted sample must satisfy total = used + free, in_use_pct in
    range, and timestamps strictly increasing per host."""
    hosts, patterns, telemetry = generate_all(small_cfg)
    samples = list(itertools.islice(telemetry, 5000))

    by_host: dict[str, list[DiskTelemetry]] = {}
    for s in samples:
        by_host.setdefault(s.host_id, []).append(s)
        assert s.used_bytes + s.free_bytes == s.total_bytes
        assert 0 <= s.in_use_pct <= 100
        assert s.total_bytes > 0

    for host_samples in by_host.values():
        timestamps = [s.ts for s in host_samples]
        assert timestamps == sorted(timestamps), "timestamps must be monotonic per host"


def test_sample_count_matches_window(small_cfg: GenerationConfig) -> None:
    """Each host should produce (history_days * 24 * 60 / interval_min) samples."""
    cfg = GenerationConfig(host_count=5, history_days=2, interval_min=30, seed=42)
    hosts, patterns, telemetry = generate_all(cfg)
    samples = list(telemetry)
    expected_per_host = (2 * 24 * 60) // 30  # 96
    counts = Counter(s.host_id for s in samples)
    for host_id, count in counts.items():
        assert count == expected_per_host
