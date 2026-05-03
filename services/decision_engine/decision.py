"""Decision Engine — Zone 3 of the architecture.

Combines ML confidence + LLM recommendation + rule signals into a single
0–1 confidence score, then routes:
  >= 0.85  → auto_remediate     (Remediation Engine runs the playbook)
  >= 0.75  → agentask           (chatbot asks for human approval)
  <  0.75  → ticket_only        (ServiceNow ticket only, no automated action)

Thresholds match the diagram. The score formula is intentionally simple
and explainable — IT-Ops governance demands the operator can read the
audit trail and understand why the system did what it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shared.config import settings

LLMRecommendation = Literal["clean", "escalate_anomaly", "no_action"]
RouteDecision = Literal["auto_remediate", "agentask", "ticket_only"]


@dataclass
class DecisionInput:
    # ML signals
    anomaly_score: float                # 0..1 from XGBoost
    forecast_7d_pct: float | None       # Prophet
    hours_to_90pct: float | None        # Prophet
    # LLM signals
    llm_recommendation: LLMRecommendation
    llm_self_confidence: float          # 0..1 from agent's structured output
    rag_doc_count: int                  # how many runbook docs grounded the decision
    # Host-level context
    environment: str                    # "prod" / "staging" / "dev"
    role: str                           # "web", "app", "db", etc.


@dataclass
class DecisionResult:
    confidence_score: float
    decision: RouteDecision
    rationale: list[str] = field(default_factory=list)


def score_and_route(d: DecisionInput) -> DecisionResult:
    rationale: list[str] = []
    score = 0.0

    # --- Component 1: LLM self-confidence (40% of score) ---------------
    llm_component = max(0.0, min(1.0, d.llm_self_confidence)) * 0.40
    score += llm_component
    rationale.append(f"LLM self-confidence {d.llm_self_confidence:.2f} → +{llm_component:.2f}")

    # --- Component 2: ML signal alignment with LLM rec (30%) ----------
    # If LLM says "clean" we want strong forecast trigger.
    # If LLM says "escalate_anomaly" we want strong anomaly score.
    # Misalignment (e.g. LLM says "no_action" but anomaly is high) hurts.
    if d.llm_recommendation == "clean":
        forecast_signal = 0.0
        if d.forecast_7d_pct is not None:
            forecast_signal = min(1.0, max(0.0, (d.forecast_7d_pct - 70) / 30))
        if d.hours_to_90pct is not None and d.hours_to_90pct < 24:
            forecast_signal = max(forecast_signal, 0.9)
        ml_component = forecast_signal * 0.30
        rationale.append(f"forecast alignment {forecast_signal:.2f} → +{ml_component:.2f}")
    elif d.llm_recommendation == "escalate_anomaly":
        ml_component = min(1.0, d.anomaly_score) * 0.30
        rationale.append(f"anomaly alignment {d.anomaly_score:.2f} → +{ml_component:.2f}")
    else:  # no_action
        # Reward agreement: low forecast + low anomaly = high confidence in noop
        ml_quiet = 1.0 - max(d.anomaly_score, (d.forecast_7d_pct or 0) / 100)
        ml_component = max(0.0, min(1.0, ml_quiet)) * 0.30
        rationale.append(f"signals quiet {ml_quiet:.2f} → +{ml_component:.2f}")
    score += ml_component

    # --- Component 3: RAG grounding (15%) -----------------------------
    # 0 docs = unsupported decision; 4+ docs = well-grounded
    rag_factor = min(1.0, d.rag_doc_count / 4.0)
    rag_component = rag_factor * 0.15
    score += rag_component
    rationale.append(f"RAG grounding ({d.rag_doc_count} docs) → +{rag_component:.2f}")

    # --- Component 4: environment risk adjustment (15%) ---------------
    # Prod is HIGHER risk → require higher confidence to auto-remediate, so
    # we *reduce* the boost. Dev is lower risk → bigger boost.
    env_boost = {"prod": 0.05, "staging": 0.10, "dev": 0.15}.get(d.environment, 0.05)
    score += env_boost
    rationale.append(f"environment={d.environment} → +{env_boost:.2f}")

    # --- Hard rule: anomaly + LLM says clean → suppress ----------------
    if d.llm_recommendation == "clean" and d.anomaly_score > 0.6:
        rationale.append(
            "OVERRIDE: anomaly_score > 0.6 with 'clean' recommendation — "
            "growth is not normal; escalating instead of cleaning"
        )
        score = min(score, settings.decision_agentask_threshold - 0.01)

    # --- Hard rule: escalate_anomaly always at least OpsGPT chat ------
    if d.llm_recommendation == "escalate_anomaly":
        score = max(score, settings.decision_agentask_threshold)
        rationale.append("escalate_anomaly → minimum OpsGPT chatbot routing")

    score = max(0.0, min(1.0, score))

    if score >= settings.decision_auto_remediate_threshold:
        decision: RouteDecision = "auto_remediate"
    elif score >= settings.decision_agentask_threshold:
        decision = "agentask"
    else:
        decision = "ticket_only"

    rationale.append(f"final={score:.3f} → {decision}")
    return DecisionResult(confidence_score=round(score, 3), decision=decision, rationale=rationale)
