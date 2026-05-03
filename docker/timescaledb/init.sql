-- TimescaleDB initial schema.
-- Holds Datadog-shaped telemetry + ML predictions + run audit.
-- The ingestion service backfills synthetic data; production would receive
-- it from Celery Beat polling Datadog.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- =========================================================================
-- HOSTS — fleet inventory
-- =========================================================================
CREATE TABLE IF NOT EXISTS hosts (
    host_id          TEXT PRIMARY KEY,
    hostname         TEXT NOT NULL,
    os               TEXT NOT NULL CHECK (os IN ('windows', 'linux')),
    environment      TEXT NOT NULL,             -- 'prod', 'staging', 'dev'
    region           TEXT NOT NULL,
    role             TEXT NOT NULL,             -- 'web', 'db', 'app', 'batch', etc.
    total_disk_gb    DOUBLE PRECISION NOT NULL,
    monitored_path   TEXT NOT NULL,             -- 'C:\' or '/'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hosts_env ON hosts (environment);
CREATE INDEX IF NOT EXISTS idx_hosts_role ON hosts (role);

-- =========================================================================
-- DISK_TELEMETRY — Datadog-shaped time series (hypertable)
-- One row per (host, device, ts). Retention 30 days.
-- =========================================================================
CREATE TABLE IF NOT EXISTS disk_telemetry (
    ts               TIMESTAMPTZ NOT NULL,
    host_id          TEXT NOT NULL REFERENCES hosts(host_id),
    device           TEXT NOT NULL,             -- 'C:', '/dev/sda1', etc.
    total_bytes      BIGINT NOT NULL,
    used_bytes       BIGINT NOT NULL,
    free_bytes       BIGINT NOT NULL,
    in_use_pct       DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (host_id, device, ts)
);

SELECT create_hypertable('disk_telemetry', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_telemetry_host_ts
    ON disk_telemetry (host_id, ts DESC);

-- 30-day retention per the architecture diagram
SELECT add_retention_policy('disk_telemetry', INTERVAL '30 days', if_not_exists => TRUE);

-- =========================================================================
-- ML_PREDICTIONS — Prophet forecasts + XGBoost anomaly scores per run
-- =========================================================================
CREATE TABLE IF NOT EXISTS ml_predictions (
    prediction_id        TEXT PRIMARY KEY,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    host_id              TEXT NOT NULL REFERENCES hosts(host_id),
    device               TEXT NOT NULL,
    -- Prophet output: predicted in_use_pct at each horizon
    forecast_1d_pct      DOUBLE PRECISION,
    forecast_3d_pct      DOUBLE PRECISION,
    forecast_7d_pct      DOUBLE PRECISION,
    forecast_14d_pct     DOUBLE PRECISION,
    -- Time when in_use_pct is projected to cross 90% (NULL if not within 14d)
    hours_to_90pct       DOUBLE PRECISION,
    -- XGBoost output: probability of anomalous growth pattern (0..1)
    anomaly_score        DOUBLE PRECISION NOT NULL,
    -- Whether this prediction triggered the LLM agent (per >90%/7d rule)
    triggered_agent      BOOLEAN NOT NULL DEFAULT FALSE,
    model_version        TEXT NOT NULL DEFAULT 'v1'
);

CREATE INDEX IF NOT EXISTS idx_predictions_host_ts
    ON ml_predictions (host_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_triggered
    ON ml_predictions (triggered_agent, ts DESC) WHERE triggered_agent = TRUE;

-- =========================================================================
-- AGENT_RUNS — full audit trail of LLM agent invocations
-- =========================================================================
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id               TEXT PRIMARY KEY,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at          TIMESTAMPTZ,
    host_id              TEXT NOT NULL REFERENCES hosts(host_id),
    prediction_id        TEXT REFERENCES ml_predictions(prediction_id),
    -- Decision Engine output
    confidence_score     DOUBLE PRECISION,
    decision             TEXT,                  -- 'auto_remediate' | 'agentask' | 'ticket_only'
    -- Outcome
    verdict              TEXT,                  -- 'cleaned' | 'no_action_needed' | 'escalated_anomaly'
    bytes_freed          BIGINT DEFAULT 0,
    files_deleted        INT DEFAULT 0,
    servicenow_ticket_id TEXT,
    -- Trace
    llm_reasoning        TEXT,                  -- agent summary
    tool_calls           JSONB,                 -- list of {tool, input, output}
    rag_context_ids      TEXT[],                -- which RAG docs were retrieved
    error                TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_host_started
    ON agent_runs (host_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_decision
    ON agent_runs (decision, started_at DESC);

-- =========================================================================
-- SERVICENOW_TICKETS — mock ServiceNow integration (Zone 3)
-- Created by the LLM agent when the Decision Engine routes ticket_only or
-- the verdict is escalated_anomaly. In production this would be a REST POST
-- to ServiceNow's incident table; the schema mirrors that intent.
-- =========================================================================
CREATE TABLE IF NOT EXISTS servicenow_tickets (
    ticket_id         TEXT PRIMARY KEY,            -- e.g. INC-2026-05-0001
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status            TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'assigned', 'in_progress', 'resolved', 'closed')),
    severity          TEXT NOT NULL
                        CHECK (severity IN ('P1', 'P2', 'P3', 'P4')),
    short_description TEXT NOT NULL,
    description       TEXT NOT NULL,
    host_id           TEXT REFERENCES hosts(host_id),
    assignment_group  TEXT NOT NULL,
    agent_run_id      TEXT REFERENCES agent_runs(run_id),
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tickets_status_created
    ON servicenow_tickets (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_severity
    ON servicenow_tickets (severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_host
    ON servicenow_tickets (host_id, created_at DESC);
