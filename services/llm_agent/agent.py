"""LangGraph agent — Zone 2 of the architecture.

State machine:

    fetch_context → sanitize → reason → decide → execute_or_skip → audit → END

  - fetch_context: pulls host metadata, latest ML prediction, file listing,
                    and runbook RAG context.
  - sanitize:       runs the Data Sanitizer over the assembled context.
  - reason:         calls Claude with the sanitized context, expects
                    structured JSON {recommendation, self_confidence, rationale}.
  - decide:         hands the result to the Decision Engine which produces
                    a confidence score and a route (auto_remediate / agentask /
                    ticket_only).
  - execute_or_skip: branches on the route. auto_remediate runs the
                    Remediation Engine; agentask + ticket_only just record
                    intent (Day 4 wires up the chatbot, Day 5 wires up
                    ServiceNow).
  - audit:          persists the full run to TimescaleDB agent_runs.

The graph is intentionally explicit (StateGraph with named nodes) so it
maps directly to the architecture diagram.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from shared.config import settings
from shared.db import timescale_conn
from shared.schemas import AgentRun

from services.decision_engine.decision import (
    DecisionInput,
    DecisionResult,
    score_and_route,
)
from services.remediation.executor import RemediationResult, execute as remediation_execute
from services.remediation.playbooks import get_playbook
from services.servicenow_mock.client import create_ticket_from_run
from shared.schemas import MLPrediction

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .rag import RetrievedDoc
from .sanitizer import sanitize
from .tools import (
    FileInfo,
    ToolCall,
    format_file_listing,
    format_runbook_context,
    list_files,
    search_runbooks,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    # Input
    host_id: str
    run_id: str

    # Fetched context
    host_meta: dict
    prediction: dict
    files: list[FileInfo]
    rag_docs: list[RetrievedDoc]

    # Trace
    tool_calls: list[ToolCall]
    sanitization_counts: dict[str, int]

    # LLM output
    llm_recommendation: str
    llm_self_confidence: float
    llm_rationale: str
    llm_key_evidence: list[str]
    llm_raw: str

    # Decision Engine
    decision: DecisionResult

    # Remediation
    remediation: RemediationResult | None

    # Errors
    error: str | None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def _fetch_host_meta(host_id: str) -> dict:
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hosts WHERE host_id = %s", (host_id,))
            row = cur.fetchone()
    if not row:
        raise ValueError(f"unknown host_id {host_id!r}")
    return row


def _fetch_latest_prediction(host_id: str) -> dict:
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT prediction_id, ts, host_id, device,
                       forecast_1d_pct, forecast_3d_pct, forecast_7d_pct,
                       forecast_14d_pct, hours_to_90pct, anomaly_score,
                       triggered_agent
                FROM ml_predictions
                WHERE host_id = %s
                ORDER BY ts DESC
                LIMIT 1
                """,
                (host_id,),
            )
            row = cur.fetchone()
    if not row:
        raise ValueError(f"no ML prediction yet for {host_id} — run --once first")
    # Convert datetime to string for JSON serialization in prompts
    if row.get("ts"):
        row["ts"] = row["ts"].isoformat()
    return row


def node_fetch_context(state: AgentState) -> AgentState:
    log.info("[%s] fetch_context", state["host_id"])
    host_meta = _fetch_host_meta(state["host_id"])
    prediction = _fetch_latest_prediction(state["host_id"])

    tool_calls: list[ToolCall] = []
    files, fc1 = list_files(state["host_id"], host_meta["monitored_path"], max_files=50)
    tool_calls.append(fc1)

    # Retrieve runbook context — query is shaped from host metadata + ML signal
    rag_query = (
        f"{host_meta['os']} {host_meta['role']} server "
        f"{'anomalous log growth' if prediction['anomaly_score'] > 0.5 else 'disk cleanup'} "
        f"{host_meta['monitored_path']}"
    )
    docs, fc2 = search_runbooks(rag_query, top_k=4)
    tool_calls.append(fc2)

    return {
        **state,
        "host_meta": host_meta,
        "prediction": prediction,
        "files": files,
        "rag_docs": docs,
        "tool_calls": tool_calls,
    }


def node_sanitize(state: AgentState) -> AgentState:
    log.info("[%s] sanitize", state["host_id"])
    # Sanitize the runbook content (most likely place for sensitive data)
    counts: dict[str, int] = {}
    cleaned_docs: list[RetrievedDoc] = []
    for d in state.get("rag_docs", []):
        r = sanitize(d.content)
        for cat, n in r.redactions.items():
            counts[cat] = counts.get(cat, 0) + n
        cleaned_docs.append(RetrievedDoc(
            doc_id=d.doc_id, source=d.source, title=d.title,
            content=r.sanitized, metadata=d.metadata, similarity=d.similarity,
        ))

    # Sanitize file paths too (in case any contain user emails / IPs)
    files_in = state.get("files", [])
    cleaned_files: list[FileInfo] = []
    for f in files_in:
        r = sanitize(f.path)
        for cat, n in r.redactions.items():
            counts[cat] = counts.get(cat, 0) + n
        cleaned_files.append(FileInfo(
            path=r.sanitized, size_bytes=f.size_bytes,
            age_days=f.age_days, is_active_log=f.is_active_log,
        ))

    return {**state, "rag_docs": cleaned_docs, "files": cleaned_files, "sanitization_counts": counts}


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _parse_llm_output(raw: str) -> dict:
    """Best-effort: pull the first JSON object from the response."""
    m = _JSON_BLOCK.search(raw)
    if not m:
        raise ValueError(f"no JSON found in LLM output: {raw[:200]!r}")
    return json.loads(m.group(0))


def node_reason(state: AgentState) -> AgentState:
    log.info("[%s] reason (model=%s)", state["host_id"], settings.opsgpt_llm_model)
    user_prompt = build_user_prompt(
        host_meta=state["host_meta"],
        prediction=state["prediction"],
        file_listing=format_file_listing(state["files"]),
        runbook_context=format_runbook_context(state["rag_docs"]),
    )

    llm = ChatAnthropic(
        model=settings.opsgpt_llm_model,
        max_tokens=1024,
        api_key=settings.anthropic_api_key,
    )
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])
    raw = response.content if isinstance(response.content, str) else str(response.content)

    try:
        parsed = _parse_llm_output(raw)
        recommendation = parsed.get("recommendation", "no_action")
        self_conf = float(parsed.get("self_confidence", 0.5))
        rationale = parsed.get("rationale", "")
        evidence = parsed.get("key_evidence", []) or []
    except Exception as e:  # noqa: BLE001
        log.warning("LLM output parse failed: %s; raw=%r", e, raw[:200])
        recommendation = "no_action"
        self_conf = 0.0
        rationale = f"LLM output parse error: {e}"
        evidence = []

    if recommendation not in ("clean", "escalate_anomaly", "no_action"):
        log.warning("invalid recommendation %r; defaulting to no_action", recommendation)
        recommendation = "no_action"

    return {
        **state,
        "llm_recommendation": recommendation,
        "llm_self_confidence": max(0.0, min(1.0, self_conf)),
        "llm_rationale": rationale,
        "llm_key_evidence": evidence,
        "llm_raw": raw,
    }


def node_decide(state: AgentState) -> AgentState:
    log.info("[%s] decide", state["host_id"])
    p = state["prediction"]
    h = state["host_meta"]
    di = DecisionInput(
        anomaly_score=float(p.get("anomaly_score", 0.0)),
        forecast_7d_pct=p.get("forecast_7d_pct"),
        hours_to_90pct=p.get("hours_to_90pct"),
        llm_recommendation=state["llm_recommendation"],  # type: ignore[arg-type]
        llm_self_confidence=state["llm_self_confidence"],
        rag_doc_count=len(state.get("rag_docs", [])),
        environment=h.get("environment", "prod"),
        role=h.get("role", "app"),
    )
    decision = score_and_route(di)
    log.info(
        "[%s] decision: %s (confidence=%.3f)",
        state["host_id"], decision.decision, decision.confidence_score,
    )
    return {**state, "decision": decision}


def node_execute(state: AgentState) -> AgentState:
    decision = state["decision"]
    if decision.decision != "auto_remediate":
        log.info("[%s] route=%s — skipping execution", state["host_id"], decision.decision)
        return {**state, "remediation": None}

    if state["llm_recommendation"] != "clean":
        log.info("[%s] LLM did not recommend clean — no execution", state["host_id"])
        return {**state, "remediation": None}

    h = state["host_meta"]
    role = h.get("role", "app")
    log.info("[%s] auto-remediating with playbook=%s", state["host_id"], role)
    playbook = get_playbook(role)
    result = remediation_execute(
        host_id=state["host_id"],
        monitored_path=h["monitored_path"],
        playbook=playbook,
        dry_run=False,
    )
    log.info(
        "[%s] remediation: deleted=%d, freed=%.2fGB",
        state["host_id"], result.file_count, result.bytes_freed / (1024**3),
    )
    return {**state, "remediation": result}


def node_audit(state: AgentState) -> AgentState:
    log.info("[%s] audit", state["host_id"])
    decision = state["decision"]
    remediation = state.get("remediation")

    verdict = "no_action_needed"
    if state["llm_recommendation"] == "escalate_anomaly":
        verdict = "escalated_anomaly"
    elif remediation is not None and remediation.file_count > 0:
        verdict = "cleaned"

    record = AgentRun(
        run_id=state["run_id"],
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        host_id=state["host_id"],
        prediction_id=state["prediction"].get("prediction_id"),
        confidence_score=decision.confidence_score,
        decision=decision.decision,
        verdict=verdict,
        bytes_freed=remediation.bytes_freed if remediation else 0,
        files_deleted=remediation.file_count if remediation else 0,
        servicenow_ticket_id=None,  # Day 5
        llm_reasoning=state["llm_rationale"],
        tool_calls=[asdict(tc) for tc in state.get("tool_calls", [])],
        rag_context_ids=[d.doc_id for d in state.get("rag_docs", [])],
    )

    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_runs
                  (run_id, started_at, finished_at, host_id, prediction_id,
                   confidence_score, decision, verdict, bytes_freed, files_deleted,
                   servicenow_ticket_id, llm_reasoning, tool_calls, rag_context_ids)
                VALUES
                  (%(run_id)s, %(started_at)s, %(finished_at)s, %(host_id)s,
                   %(prediction_id)s, %(confidence_score)s, %(decision)s,
                   %(verdict)s, %(bytes_freed)s, %(files_deleted)s,
                   %(servicenow_ticket_id)s, %(llm_reasoning)s,
                   %(tool_calls)s::jsonb, %(rag_context_ids)s)
                """,
                {
                    **record.model_dump(),
                    "tool_calls": json.dumps(record.tool_calls),
                },
            )
        conn.commit()

    # Create a ServiceNow ticket when the agent escalates or routes to tickets.
    # Verdicts that end in remediation (cleaned) don't get a ticket — the
    # action *is* the resolution.
    needs_ticket = (
        verdict == "escalated_anomaly" or decision.decision == "ticket_only"
    )
    if needs_ticket:
        try:
            pred_dict = state.get("prediction") or {}
            pred_obj: MLPrediction | None = None
            if pred_dict.get("prediction_id"):
                # Convert dict back to model; ts may already be ISO string
                pred_obj = MLPrediction.model_validate(pred_dict)
            ticket = create_ticket_from_run(
                agent_run=record,
                host_metadata=state["host_meta"],
                prediction=pred_obj,
            )
            log.info("[%s] ServiceNow ticket %s created (severity=%s)",
                     state["host_id"], ticket.ticket_id, ticket.severity)
        except Exception as e:  # noqa: BLE001
            log.warning("ticket creation failed: %s", e)

    return state


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph():
    """Full end-to-end graph: Monitor → Predict → Reasoning → Resolve in one shot."""
    g = StateGraph(AgentState)
    g.add_node("fetch_context", node_fetch_context)
    g.add_node("sanitize", node_sanitize)
    g.add_node("reason", node_reason)
    g.add_node("decide", node_decide)
    g.add_node("execute_or_skip", node_execute)
    g.add_node("audit", node_audit)
    g.set_entry_point("fetch_context")
    g.add_edge("fetch_context", "sanitize")
    g.add_edge("sanitize", "reason")
    g.add_edge("reason", "decide")
    g.add_edge("decide", "execute_or_skip")
    g.add_edge("execute_or_skip", "audit")
    g.add_edge("audit", END)
    return g.compile()


def build_reasoning_graph():
    """Reasoning-only subgraph: gather context, sanitize, reason, score.
    Stops before any side effects (no execute, no audit, no ticket).
    The UI uses this for the 'Reasoning' button — operator inspects what
    the agent recommends BEFORE committing to action."""
    g = StateGraph(AgentState)
    g.add_node("fetch_context", node_fetch_context)
    g.add_node("sanitize", node_sanitize)
    g.add_node("reason", node_reason)
    g.add_node("decide", node_decide)
    g.set_entry_point("fetch_context")
    g.add_edge("fetch_context", "sanitize")
    g.add_edge("sanitize", "reason")
    g.add_edge("reason", "decide")
    g.add_edge("decide", END)
    return g.compile()


def build_resolve_graph():
    """Resolve subgraph: takes a fully-decided state, executes (if route is
    auto_remediate) and writes the audit row + ticket. The UI uses this for
    the 'Resolve' button after the operator has reviewed the reasoning."""
    g = StateGraph(AgentState)
    g.add_node("execute_or_skip", node_execute)
    g.add_node("audit", node_audit)
    g.set_entry_point("execute_or_skip")
    g.add_edge("execute_or_skip", "audit")
    g.add_edge("audit", END)
    return g.compile()


def run_agent(host_id: str, run_id: str | None = None) -> AgentState:
    """One-shot run — equivalent to run_reasoning followed by run_resolve."""
    graph = build_graph()
    initial: AgentState = {
        "host_id": host_id,
        "run_id": run_id or f"run-{uuid.uuid4().hex[:12]}",
    }
    return graph.invoke(initial)


def run_reasoning(host_id: str, run_id: str | None = None) -> AgentState:
    """Reasoning only — no side effects. Returns state with decision but
    no audit row, no ticket, no remediation."""
    graph = build_reasoning_graph()
    initial: AgentState = {
        "host_id": host_id,
        "run_id": run_id or f"run-{uuid.uuid4().hex[:12]}",
    }
    return graph.invoke(initial)


def run_resolve(state: AgentState) -> AgentState:
    """Resolve — takes a state from run_reasoning, executes the playbook
    (if route is auto_remediate) and writes the audit row + ticket."""
    if "decision" not in state:
        raise ValueError(
            "run_resolve requires a state from run_reasoning (no decision found)"
        )
    graph = build_resolve_graph()
    return graph.invoke(state)
