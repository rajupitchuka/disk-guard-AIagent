"""Centralized config loaded from environment (with .env fallback).

All services in opsgpt-disk-prediction-poc read settings through this module.
Override via environment variables — no setting is hardcoded in service code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pre-load .env into os.environ. By default, dotenv won't overwrite vars that
# are already set — but pydantic-settings will see an EMPTY OS env var (set
# by some parent process) as "set" and ignore the .env value. Override=True
# fixes that for our flow: .env wins for fields we care about.
_env_path = Path.cwd() / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Anthropic / Claude ---
    anthropic_api_key: str = ""
    opsgpt_llm_model: str = "claude-haiku-4-5"

    # --- TimescaleDB ---
    timescale_host: str = "localhost"
    timescale_port: int = 5432
    timescale_db: str = "opsgpt_telemetry"
    timescale_user: str = "opsgpt"
    timescale_password: str = "opsgpt_dev_password"

    # --- pgvector ---
    pgvector_host: str = "localhost"
    pgvector_port: int = 5433
    pgvector_db: str = "opsgpt_rag"
    pgvector_user: str = "opsgpt"
    pgvector_password: str = "opsgpt_dev_password"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- Synthetic data generation ---
    synthetic_host_count: int = 3000
    synthetic_telemetry_interval_min: int = 5
    synthetic_history_days: int = 7

    # --- Pipeline cadence ---
    ingestion_interval_min: int = 15
    ml_run_interval_min: int = 15
    ml_predict_horizons_days: str = "1,3,7,14"
    ml_trigger_fill_pct: float = 90.0
    ml_trigger_horizon_days: int = 7

    # --- Decision Engine confidence thresholds ---
    decision_auto_remediate_threshold: float = 0.85
    decision_agentask_threshold: float = 0.75

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    @property
    def timescale_dsn(self) -> str:
        return (
            f"postgresql://{self.timescale_user}:{self.timescale_password}"
            f"@{self.timescale_host}:{self.timescale_port}/{self.timescale_db}"
        )

    @property
    def pgvector_dsn(self) -> str:
        return (
            f"postgresql://{self.pgvector_user}:{self.pgvector_password}"
            f"@{self.pgvector_host}:{self.pgvector_port}/{self.pgvector_db}"
        )

    @property
    def predict_horizon_days(self) -> list[int]:
        return [int(x.strip()) for x in self.ml_predict_horizons_days.split(",") if x.strip()]


# Singleton — import-time read. .env was already loaded above via dotenv,
# so pydantic-settings reads from os.environ directly.
settings = Settings()
