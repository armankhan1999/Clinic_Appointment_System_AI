"""Structured JSON logging with a per-request correlation id (NFR-11, IMP-11).

Log events must never carry chat text, names, phone numbers or secrets (NFR-06). The redaction
processor is a safety net for mistakes, not a licence to pass such values.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "phone",
        "full_name",
        "name",
        "text",
        "message",
        "token",
        "password",
        "api_key",
        "authorization",
        "cookie",
    }
)
# httpx logs full request URLs at INFO; Telegram URLs embed the bot token.
QUIET_LOGGERS = ("httpx", "httpcore")


def new_request_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def bind_request_id(request_id: str) -> Iterator[str]:
    token = request_id_var.set(request_id)
    try:
        yield request_id
    finally:
        request_id_var.reset(token)


def _add_request_id(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    request_id = request_id_var.get()
    if request_id is not None:
        event.setdefault("request_id", request_id)
    return event


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in SENSITIVE_KEYS.intersection(event):
        event[key] = "[redacted]"
    return event


def configure_logging(level: str) -> None:
    numeric_level = logging.getLevelNamesMapping()[level.upper()]
    logging.basicConfig(level=numeric_level, stream=sys.stdout, format="%(message)s", force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
