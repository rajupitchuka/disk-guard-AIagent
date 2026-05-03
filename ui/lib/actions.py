"""Action handlers for UI buttons. Each returns a structured result the page
renders as a status banner."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from data.fill_disk import clear as fill_clear
from data.fill_disk import fill as fill_fill
from services.llm_agent.agent import run_agent, run_reasoning, run_resolve
from services.ml_engine.pipeline import run_predictions_for_host

log = logging.getLogger(__name__)


@dataclass
class ActionResult:
    ok: bool
    message: str
    detail: dict[str, Any]


def fill_disk(host_id: str, gb: float, with_backfill_min: int = 60) -> ActionResult:
    try:
        result = fill_fill(host_id, gb, backfill_minutes=with_backfill_min)
        return ActionResult(
            ok=True,
            message=f"Wrote {gb:.1f} GB into {host_id}; "
                    f"backfilled {result['samples_backfilled']} samples.",
            detail=result,
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(ok=False, message=f"fill failed: {e}", detail={})


def clear_disk(host_id: str) -> ActionResult:
    try:
        result = fill_clear(host_id)
        return ActionResult(
            ok=True,
            message=f"Cleared synthetic junk files on {host_id}.",
            detail=result,
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(ok=False, message=f"clear failed: {e}", detail={})


def run_ml(host_id: str) -> ActionResult:
    try:
        prediction = run_predictions_for_host(host_id)
        return ActionResult(
            ok=True,
            message=(
                f"ML prediction recorded for {host_id} — "
                f"anomaly={prediction.anomaly_score:.3f}, "
                f"forecast_7d={prediction.forecast_7d_pct:.1f}%, "
                f"hours_to_90={prediction.hours_to_90pct or 'n/a'}, "
                f"triggered={prediction.triggered_agent}"
            ),
            detail=prediction.model_dump(),
        )
    except Exception as e:  # noqa: BLE001
        return ActionResult(ok=False, message=f"ML run failed: {e}", detail={})


def run_llm_agent(host_id: str) -> ActionResult:
    """Full one-shot agent run (kept for the agent CLI / Audit-page tests)."""
    try:
        state = run_agent(host_id)
        decision = state.get("decision")
        remediation = state.get("remediation")
        return ActionResult(
            ok=True,
            message=(
                f"Agent done — recommendation={state.get('llm_recommendation')}, "
                f"decision={decision.decision if decision else '?'} "
                f"(conf={decision.confidence_score if decision else 0:.3f})"
            ),
            detail={
                "run_id": state.get("run_id"),
                "llm_recommendation": state.get("llm_recommendation"),
                "llm_self_confidence": state.get("llm_self_confidence"),
                "llm_rationale": state.get("llm_rationale"),
                "llm_key_evidence": state.get("llm_key_evidence", []),
                "decision": decision.decision if decision else None,
                "decision_score": decision.confidence_score if decision else None,
                "decision_rationale": decision.rationale if decision else [],
                "files_deleted": remediation.file_count if remediation else 0,
                "bytes_freed": remediation.bytes_freed if remediation else 0,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("agent run failed")
        return ActionResult(ok=False, message=f"agent run failed: {e}", detail={})


def run_reasoning_only(host_id: str) -> ActionResult:
    """Stage 3 of the demo: reason + decide, NO side effects yet.

    Returns the full LangGraph state in `detail['state']` so the UI can
    pass it back to run_resolve_action when the operator clicks Resolve.
    """
    try:
        state = run_reasoning(host_id)
        decision = state.get("decision")
        return ActionResult(
            ok=True,
            message=(
                f"Reasoning complete — recommendation={state.get('llm_recommendation')}, "
                f"decision={decision.decision if decision else '?'} "
                f"(conf={decision.confidence_score if decision else 0:.3f})"
            ),
            detail={
                "state": state,  # carry forward to Resolve
                "run_id": state.get("run_id"),
                "llm_recommendation": state.get("llm_recommendation"),
                "llm_self_confidence": state.get("llm_self_confidence"),
                "llm_rationale": state.get("llm_rationale"),
                "llm_key_evidence": state.get("llm_key_evidence", []),
                "decision": decision.decision if decision else None,
                "decision_score": decision.confidence_score if decision else None,
                "decision_rationale": decision.rationale if decision else [],
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("reasoning failed")
        return ActionResult(ok=False, message=f"reasoning failed: {e}", detail={})


def run_resolve_action(state: dict) -> ActionResult:
    """Stage 4 of the demo: take a reasoning state and apply the decision.
    auto_remediate executes the playbook; agentask + ticket_only just write
    the audit row (and a ServiceNow ticket where appropriate)."""
    try:
        final_state = run_resolve(state)
        decision = final_state.get("decision")
        remediation = final_state.get("remediation")
        files = remediation.file_count if remediation else 0
        gb = (remediation.bytes_freed if remediation else 0) / (1024**3)
        action_summary = {
            "auto_remediate": (
                f"Auto-remediated: {files} files deleted, {gb:.2f} GB freed"
            ) if remediation and files else "Auto-remediate route chosen but no remediation executed (LLM did not recommend clean — escalation path).",
            "agentask": "Pending operator approval — see OpsGPT chat page.",
            "ticket_only": "Routed to ServiceNow ticket only (confidence below auto-remediate threshold).",
        }.get(decision.decision if decision else "", "(no action)")
        return ActionResult(
            ok=True,
            message=action_summary,
            detail={
                "decision": decision.decision if decision else None,
                "files_deleted": files,
                "bytes_freed": remediation.bytes_freed if remediation else 0,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("resolve failed")
        return ActionResult(ok=False, message=f"resolve failed: {e}", detail={})
