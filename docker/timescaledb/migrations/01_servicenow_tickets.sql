-- Migration 01: ServiceNow tickets table
-- Apply to a running stack with:
--   docker exec opsgpt_timescaledb psql -U opsgpt -d opsgpt_telemetry \
--     < docker/timescaledb/migrations/01_servicenow_tickets.sql
--
-- Fresh installs pick this up via init.sql (which is the source of truth).

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
