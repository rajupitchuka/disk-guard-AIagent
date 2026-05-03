"""Pydantic models — the canonical shape of every domain object that flows
through the pipeline. Used by the data generator, ingestion, ML engine, agent,
and UI to keep field names and types in lockstep with the DB schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

OS = Literal["windows", "linux"]
Environment = Literal["prod", "staging", "dev"]
Decision = Literal["auto_remediate", "agentask", "ticket_only"]
Verdict = Literal["cleaned", "no_action_needed", "escalated_anomaly"]
TicketStatus = Literal["new", "assigned", "in_progress", "resolved", "closed"]
Severity = Literal["P1", "P2", "P3", "P4"]


class Host(BaseModel):
    host_id: str
    hostname: str
    os: OS
    environment: Environment
    region: str
    role: str
    total_disk_gb: float
    monitored_path: str
    created_at: Optional[datetime] = None


class DiskTelemetry(BaseModel):
    """One Datadog-shaped sample, normalized by the ingestion service."""
    ts: datetime
    host_id: str
    device: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    in_use_pct: float = Field(ge=0, le=100)


class MLPrediction(BaseModel):
    """Output of one ML run for one (host, device) at one timestamp."""
    prediction_id: str
    ts: datetime
    host_id: str
    device: str
    forecast_1d_pct: Optional[float] = None
    forecast_3d_pct: Optional[float] = None
    forecast_7d_pct: Optional[float] = None
    forecast_14d_pct: Optional[float] = None
    hours_to_90pct: Optional[float] = None
    anomaly_score: float = Field(ge=0, le=1)
    triggered_agent: bool = False
    model_version: str = "v1"


class AgentRun(BaseModel):
    """Audit record for one LLM agent invocation."""
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    host_id: str
    prediction_id: Optional[str] = None
    confidence_score: Optional[float] = None
    decision: Optional[Decision] = None
    verdict: Optional[Verdict] = None
    bytes_freed: int = 0
    files_deleted: int = 0
    servicenow_ticket_id: Optional[str] = None
    llm_reasoning: Optional[str] = None
    tool_calls: list[dict] = Field(default_factory=list)
    rag_context_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class ServiceNowTicket(BaseModel):
    """One row from servicenow_tickets — mirrors the ServiceNow Incident shape."""
    ticket_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    status: TicketStatus = "new"
    severity: Severity
    short_description: str
    description: str
    host_id: Optional[str] = None
    assignment_group: str
    agent_run_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
