"""Smoke test that config loads with sensible defaults and computed properties
work."""

from __future__ import annotations

from shared.config import Settings


def test_defaults_load() -> None:
    s = Settings(_env_file=None)
    assert s.opsgpt_llm_model.startswith("claude-")
    assert s.synthetic_host_count > 0
    assert s.ml_predict_horizons_days == "1,3,7,14"
    assert s.predict_horizon_days == [1, 3, 7, 14]


def test_dsn_format() -> None:
    s = Settings(_env_file=None)
    assert s.timescale_dsn.startswith("postgresql://")
    assert "opsgpt_telemetry" in s.timescale_dsn
    assert s.pgvector_dsn.startswith("postgresql://")
    assert "opsgpt_rag" in s.pgvector_dsn


def test_decision_thresholds_match_diagram() -> None:
    s = Settings(_env_file=None)
    # > 0.85 → auto remediate, > 0.75 → OpsGPT chat, < 0.75 → ticket only
    assert s.decision_auto_remediate_threshold == 0.85
    assert s.decision_opsgpt_chat_threshold == 0.75

