"""Plain tool-calling loop (AGT-14): the model chooses; code validates, executes and audits."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.llm import LLM, LlmTurn, LlmUnavailableError, ModelTurn, ToolCall, ToolResults, UserText
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import ToolContext, ToolRegistry, ToolResult
from clinic.domain.results import ResultCode
from clinic.observability import safe_exception_fields
from clinic.services.audit import AuditService

log = structlog.get_logger(__name__)

type StopReason = Literal["reply", "limit", "llm_error"]


@dataclass(frozen=True)
class AuditEntry:
    actor_id: str
    action: str
    args: dict[str, Any]
    result: str
    patient_id: UUID
    latency_ms: int
    request_id: str


@dataclass(frozen=True)
class AgentOutcome:
    text: str | None
    stopped: StopReason
    tool_calls_made: int
    tool_results: tuple[tuple[str, ToolResult], ...] = ()


type AuditWriter = Callable[[AuditEntry], Awaitable[None]]


class AgentLoop:
    def __init__(
        self,
        llm: LLM,
        registry: ToolRegistry,
        write_audit: AuditWriter,
        *,
        actor_id: str,
        max_tool_calls: int = 5,
        budget_seconds: float = 8.0,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._write_audit = write_audit
        self._actor_id = actor_id
        self._max_tool_calls = max_tool_calls
        self._budget = budget_seconds

    async def run(
        self, ctx: ToolContext, memory: ConversationMemory, user_key: int, user_text: str, system_prompt: str
    ) -> AgentOutcome:
        """The budget covers model calls, tool execution and audit writes together (E1-S1-AC3)."""
        try:
            async with asyncio.timeout(self._budget):
                return await self._run(ctx, memory, user_key, user_text, system_prompt)
        except TimeoutError:
            log.warning("agent_budget_exhausted", budget_s=self._budget)
            return AgentOutcome(None, "llm_error", 0)

    async def _run(
        self, ctx: ToolContext, memory: ConversationMemory, user_key: int, user_text: str, system_prompt: str
    ) -> AgentOutcome:
        exchange: list[Any] = [UserText(user_text)]
        calls_made = 0
        results_seen: list[tuple[str, ToolResult]] = []
        while True:
            turn = await self._generate(system_prompt, memory.history(user_key) + exchange)
            if turn is None:
                return AgentOutcome(None, "llm_error", calls_made, tuple(results_seen))
            exchange.append(ModelTurn(turn))
            if not turn.tool_calls:
                text = (turn.text or "").strip()
                if not text:
                    log.warning("agent_empty_reply")
                    return AgentOutcome(None, "llm_error", calls_made, tuple(results_seen))
                memory.append(user_key, exchange)
                return AgentOutcome(text, "reply", calls_made, tuple(results_seen))
            results: list[tuple[ToolCall, ToolResult]] = []
            for call in turn.tool_calls:
                if calls_made >= self._max_tool_calls:
                    log.warning("agent_tool_limit", limit=self._max_tool_calls)
                    return AgentOutcome(None, "limit", calls_made, tuple(results_seen))
                calls_made += 1
                result = await self._execute(ctx, call)
                results.append((call, result))
                results_seen.append((call.name, result))
            exchange.append(ToolResults(results))

    async def _generate(self, system: str, transcript: list[Any]) -> LlmTurn | None:
        try:
            return await self._llm.generate(system=system, transcript=transcript, tools=self._registry.specs)
        except LlmUnavailableError:
            return None

    async def _execute(self, ctx: ToolContext, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        spec = self._registry.get(call.name)
        action = call.name if spec is not None else "unknown_tool"
        audit_args: dict[str, Any] = {}
        if spec is None:
            result = ToolResult(ResultCode.INVALID_ARGS, {"error": "unknown tool"})
        else:
            try:
                args = spec.args_model.model_validate(call.args)
            except ValidationError as exc:
                # Only declared field names reach the audit log: unexpected keys are model-invented text.
                known = set(spec.args_model.model_fields)
                audit_args = {
                    "invalid_fields": sorted(
                        {str(e["loc"][0]) for e in exc.errors() if e["loc"] and e["loc"][0] in known}
                    ),
                    "unexpected_fields": sum(1 for e in exc.errors() if e["type"] == "extra_forbidden"),
                }
                result = ToolResult(
                    ResultCode.INVALID_ARGS,
                    {
                        "errors": [
                            {"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()
                        ]
                    },
                )
            else:
                audit_args = args.model_dump(mode="json", exclude_none=True)
                try:
                    result = await spec.executor(ctx, args)
                except Exception as exc:
                    # The model gets a generic error; operators get the type and code location only.
                    log.error("tool_failed", tool=spec.name, **safe_exception_fields(exc))
                    result = ToolResult(
                        ResultCode.ERROR, {"error": "the tool failed, try again or offer staff help"}
                    )
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info("agent_tool_call", tool=action, result=result.code.value, latency_ms=latency_ms)
        try:
            await self._write_audit(self._entry(ctx, action, audit_args, result, latency_ms))
        except Exception as exc:  # the reply must not be lost; the failure is logged for operators
            log.error("audit_write_failed", tool=action, **safe_exception_fields(exc))
        return result

    def _entry(
        self, ctx: ToolContext, action: str, audit_args: dict[str, Any], result: ToolResult, latency_ms: int
    ) -> AuditEntry:
        return AuditEntry(
            actor_id=self._actor_id,
            action=action,
            args=audit_args,
            result=result.code.value,
            patient_id=ctx.patient_id,
            latency_ms=latency_ms,
            request_id=ctx.request_id,
        )


def db_audit_writer(session_factory: async_sessionmaker[AsyncSession]) -> AuditWriter:
    """Persist each tool call to audit_log in its own transaction (E7-S2-AC1)."""

    async def write(entry: AuditEntry) -> None:
        async with session_factory() as session, session.begin():
            AuditService.record(
                session,
                actor_type="agent",
                actor_id=entry.actor_id,
                action=entry.action,
                args=entry.args,
                result=entry.result,
                patient_id=entry.patient_id,
                latency_ms=entry.latency_ms,
                request_id=entry.request_id,
            )

    return write
