"""Decision Engine tests — pure-function scoring, no DB or LLM."""

from __future__ import annotations

from services.decision_engine.decision import DecisionInput, score_and_route


def _make(**overrides) -> DecisionInput:
    base = dict(
        anomaly_score=0.05,
        forecast_7d_pct=45.0,
        hours_to_90pct=None,
        llm_recommendation="no_action",
        llm_self_confidence=0.9,
        rag_doc_count=4,
        environment="prod",
        role="app",
    )
    base.update(overrides)
    return DecisionInput(**base)


def test_strong_clean_signal_auto_remediates_in_dev() -> None:
    """Confident LLM + imminent forecast + dev environment → auto remediate."""
    d = _make(
        llm_recommendation="clean",
        llm_self_confidence=0.95,
        forecast_7d_pct=98.0,
        hours_to_90pct=12.0,
        environment="dev",
    )
    r = score_and_route(d)
    assert r.decision == "auto_remediate"
    assert r.confidence_score >= 0.85


def test_anomaly_recommendation_at_least_opsgpt_chat() -> None:
    """escalate_anomaly should never route to ticket_only."""
    d = _make(
        llm_recommendation="escalate_anomaly",
        llm_self_confidence=0.4,
        anomaly_score=0.997,
    )
    r = score_and_route(d)
    assert r.decision in ("opsgpt_chat", "auto_remediate")


def test_clean_with_high_anomaly_is_overridden() -> None:
    """If LLM says 'clean' but anomaly is high, decision engine suppresses
    auto-remediation — anomalous growth shouldn't be cleaned automatically
    even if the LLM doesn't catch the contradiction."""
    d = _make(
        llm_recommendation="clean",
        llm_self_confidence=0.95,
        anomaly_score=0.95,
        forecast_7d_pct=98.0,
        environment="dev",
    )
    r = score_and_route(d)
    assert r.decision != "auto_remediate"


def test_low_self_confidence_drops_to_ticket() -> None:
    d = _make(
        llm_recommendation="clean",
        llm_self_confidence=0.2,
        forecast_7d_pct=92.0,
        rag_doc_count=0,
        environment="prod",
    )
    r = score_and_route(d)
    assert r.decision == "ticket_only"


def test_no_action_with_quiet_signals_is_high_confidence() -> None:
    """If everything is quiet and LLM confidently says no_action, that's
    a HIGH-confidence noop, not a low one."""
    d = _make(
        llm_recommendation="no_action",
        llm_self_confidence=0.95,
        anomaly_score=0.01,
        forecast_7d_pct=22.0,
    )
    r = score_and_route(d)
    assert r.decision in ("auto_remediate", "opsgpt_chat")  # high confidence


def test_rag_grounding_helps() -> None:
    weak = _make(rag_doc_count=0)
    strong = _make(rag_doc_count=4)
    assert score_and_route(strong).confidence_score > score_and_route(weak).confidence_score
