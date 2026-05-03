"""ServiceNow mock — pure-function classification tests (no DB)."""

from __future__ import annotations

from services.servicenow_mock.client import _classify


def test_anomaly_routes_to_app_team_p2() -> None:
    sev, group, short = _classify(
        decision="auto_remediate",
        verdict="escalated_anomaly",
        role="app",
        hours_to_90pct=None,
        anomaly_score=0.95,
    )
    assert sev == "P2"
    assert group == "App-Support-app"
    assert "Anomalous" in short


def test_anomaly_for_db_role_routes_correctly() -> None:
    sev, group, _ = _classify(
        decision="auto_remediate",
        verdict="escalated_anomaly",
        role="db",
        hours_to_90pct=None,
        anomaly_score=0.95,
    )
    assert group == "App-Support-db"


def test_imminent_breach_is_p2_capacity() -> None:
    sev, group, _ = _classify(
        decision="ticket_only",
        verdict="no_action_needed",
        role="web",
        hours_to_90pct=12.0,
        anomaly_score=0.05,
    )
    assert sev == "P2"
    assert group == "Infra-Capacity"


def test_far_future_breach_is_p3() -> None:
    sev, group, _ = _classify(
        decision="ticket_only",
        verdict="no_action_needed",
        role="web",
        hours_to_90pct=200.0,
        anomaly_score=0.05,
    )
    assert sev == "P3"
    assert group == "Infra-Capacity"


def test_default_review_route() -> None:
    sev, _, _ = _classify(
        decision=None,
        verdict=None,
        role="app",
        hours_to_90pct=None,
        anomaly_score=None,
    )
    assert sev == "P3"
