"""Sanitizer tests — runs without DB or LLM."""

from __future__ import annotations

from services.llm_agent.sanitizer import sanitize, sanitize_dict


def test_strips_aws_access_key() -> None:
    text = "user logged in from AKIAIOSFODNN7EXAMPLE successfully"
    r = sanitize(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in r.sanitized
    assert "[REDACTED:AWS_ACCESS_KEY]" in r.sanitized
    assert r.redactions["AWS_ACCESS_KEY"] == 1


def test_strips_anthropic_key() -> None:
    text = "ANTHROPIC_API_KEY=sk-ant-test1234567890abcdef in env"
    r = sanitize(text)
    assert "sk-ant-test" not in r.sanitized
    assert r.redactions.get("ANTHROPIC_KEY", 0) >= 1


def test_strips_email() -> None:
    text = "Notification sent to alice@example.com and bob@corp.io"
    r = sanitize(text)
    assert "alice@example.com" not in r.sanitized
    assert "bob@corp.io" not in r.sanitized
    assert r.redactions["EMAIL"] == 2


def test_strips_ipv4() -> None:
    text = "Host 10.0.5.42 connected to 192.168.1.1 at 03:14"
    r = sanitize(text)
    assert "10.0.5.42" not in r.sanitized
    assert r.redactions["IPV4"] == 2


def test_strips_url_credentials() -> None:
    text = "Connection string: postgres://admin:hunter2@db.internal:5432/foo"
    r = sanitize(text)
    assert "admin:hunter2@" not in r.sanitized
    assert r.redactions["URL_CRED"] == 1


def test_strips_password_flag() -> None:
    text = "Running: mysql --password=secret123 --host=db"
    r = sanitize(text)
    assert "secret123" not in r.sanitized


def test_strips_private_key() -> None:
    text = (
        "key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\nend"
    )
    r = sanitize(text)
    assert "MIIEpAIBAAKCAQEA" not in r.sanitized
    assert r.redactions["PRIVATE_KEY"] == 1


def test_clean_text_passes_through() -> None:
    text = "Disk usage on /var/log is 85.2%, threshold 90%."
    r = sanitize(text)
    assert r.sanitized == text
    assert r.total_redactions == 0


def test_sanitize_dict_processes_strings_only() -> None:
    d = {"path": "/var/log/access.log", "size": 12345, "user_email": "alice@x.com"}
    cleaned, counts = sanitize_dict(d)
    assert cleaned["size"] == 12345  # untouched
    assert "alice@x.com" not in cleaned["user_email"]
    assert counts["EMAIL"] == 1
