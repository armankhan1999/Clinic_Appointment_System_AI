import json
import logging

import pytest
import structlog

from clinic.observability import bind_request_id, configure_logging, new_request_id, request_id_var


def _last_json_line(captured: str) -> dict[str, object]:
    lines = [line for line in captured.splitlines() if line.strip()]
    parsed: dict[str, object] = json.loads(lines[-1])
    return parsed


def test_log_lines_are_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    with bind_request_id("req-12345678"):
        structlog.get_logger("test").info("tool_called", tool="list_doctors", latency_ms=12)
    event = _last_json_line(capsys.readouterr().out)
    assert event["event"] == "tool_called"
    assert event["request_id"] == "req-12345678"
    assert event["tool"] == "list_doctors"
    assert event["level"] == "info"
    assert "timestamp" in event


def test_request_id_is_unbound_after_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    with bind_request_id("req-abcdefgh"):
        assert request_id_var.get() == "req-abcdefgh"
    assert request_id_var.get() is None
    structlog.get_logger("test").info("after")
    assert "request_id" not in _last_json_line(capsys.readouterr().out)


def test_sensitive_keys_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.get_logger("test").info("oops", phone="+919876543210", text="I have chest pain", token="abc")
    event = _last_json_line(capsys.readouterr().out)
    assert event["phone"] == "[redacted]"
    assert event["text"] == "[redacted]"
    assert event["token"] == "[redacted]"


def test_http_client_loggers_cannot_leak_bot_token_urls() -> None:
    configure_logging("DEBUG")
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_new_request_ids_are_unique_and_header_safe() -> None:
    ids = {new_request_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 32 and i.isalnum() for i in ids)
