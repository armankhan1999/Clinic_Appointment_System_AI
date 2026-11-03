"""Agent loop: AGT-06 (5 tool calls max), E7-S3-AC3 (invalid args), E2-S3-AC5 (patient id), E7-S2-AC1."""

import asyncio
import time
import uuid
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from clinic.agent.llm import ModelTurn, ToolResults, UserText
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import ToolContext, ToolRegistry, ToolResult, ToolSpec
from clinic.domain.results import ResultCode

from .agent_doubles import UNAVAILABLE, ScriptedLLM, SlowLLM, call_turn, text_turn

PATIENT = uuid.uuid4()


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str = Field(max_length=10)


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[ToolContext, EchoArgs]] = []
        self.fail = fail

    async def __call__(self, ctx: ToolContext, args: EchoArgs) -> ToolResult:
        self.calls.append((ctx, args))
        if self.fail:
            raise RuntimeError("database exploded")
        return ToolResult(ResultCode.OK, {"echo": args.word})


def make_loop(llm: Any, recorder: Recorder, audit: list[AuditEntry], **kwargs: Any) -> AgentLoop:
    registry = ToolRegistry([ToolSpec("echo", "Echo a word.", EchoArgs, recorder)])

    async def write_audit(entry: AuditEntry) -> None:
        audit.append(entry)

    return AgentLoop(llm, registry, write_audit, actor_id="test-model", **kwargs)


def ctx() -> ToolContext:
    return ToolContext(patient_id=PATIENT, request_id="req-1", services=None)


async def test_plain_text_reply() -> None:
    audit: list[AuditEntry] = []
    llm = ScriptedLLM(text_turn("Hello!"))
    outcome = await make_loop(llm, Recorder(), audit).run(ctx(), ConversationMemory(), 1, "hi", "system")
    assert (outcome.text, outcome.stopped, outcome.tool_calls_made) == ("Hello!", "reply", 0)
    assert audit == []


async def test_tool_call_runs_once_and_result_goes_back_to_the_llm() -> None:
    audit: list[AuditEntry] = []
    recorder = Recorder()
    llm = ScriptedLLM(call_turn(("echo", {"word": "hi"})), text_turn("You said hi"))
    outcome = await make_loop(llm, recorder, audit).run(ctx(), ConversationMemory(), 1, "say hi", "system")
    assert outcome.text == "You said hi"
    assert outcome.tool_calls_made == 1
    assert [args.word for _, args in recorder.calls] == ["hi"]
    second_transcript = llm.transcripts[1]
    assert isinstance(second_transcript[0], UserText)
    assert isinstance(second_transcript[1], ModelTurn)
    results = second_transcript[2]
    assert isinstance(results, ToolResults)
    assert results.results[0][1] == ToolResult(ResultCode.OK, {"echo": "hi"})
    [entry] = audit
    assert (entry.action, entry.args, entry.result, entry.patient_id) == (
        "echo",
        {"word": "hi"},
        "OK",
        PATIENT,
    )
    assert entry.latency_ms >= 0
    assert entry.request_id == "req-1"


async def test_patient_id_comes_from_the_session_not_the_llm() -> None:
    audit: list[AuditEntry] = []
    recorder = Recorder()
    llm = ScriptedLLM(
        call_turn(("echo", {"word": "hi", "patient_id": str(uuid.uuid4())})),
        call_turn(("echo", {"word": "hi"})),
        text_turn("done"),
    )
    await make_loop(llm, recorder, audit).run(ctx(), ConversationMemory(), 1, "x", "system")
    assert len(recorder.calls) == 1, "the call carrying patient_id must be rejected"
    assert recorder.calls[0][0].patient_id == PATIENT
    assert [e.result for e in audit] == ["INVALID_ARGS", "OK"]


@pytest.mark.parametrize("bad_args", [{"word": "x" * 50}, {}, {"word": 5}])
async def test_invalid_arguments_are_not_executed_and_go_back_as_errors(bad_args: dict[str, Any]) -> None:
    audit: list[AuditEntry] = []
    recorder = Recorder()
    llm = ScriptedLLM(call_turn(("echo", bad_args)), text_turn("sorry"))
    outcome = await make_loop(llm, recorder, audit).run(ctx(), ConversationMemory(), 1, "x", "system")
    assert recorder.calls == []
    assert outcome.text == "sorry"
    results = llm.transcripts[1][2]
    assert isinstance(results, ToolResults)
    code = results.results[0][1].code
    assert code == ResultCode.INVALID_ARGS
    assert audit[0].result == "INVALID_ARGS"
    assert "x" * 50 not in repr(audit[0].args), "unvalidated input must not reach the audit log"


async def test_unknown_tool_is_rejected() -> None:
    audit: list[AuditEntry] = []
    llm = ScriptedLLM(call_turn(("drop_tables", {})), text_turn("ok"))
    await make_loop(llm, Recorder(), audit).run(ctx(), ConversationMemory(), 1, "x", "system")
    results = llm.transcripts[1][2]
    assert isinstance(results, ToolResults)
    assert results.results[0][1].code == ResultCode.INVALID_ARGS
    assert audit[0].action == "unknown_tool"


async def test_stops_after_five_tool_calls() -> None:
    audit: list[AuditEntry] = []
    recorder = Recorder()
    llm = ScriptedLLM(*[call_turn(("echo", {"word": "again"})) for _ in range(6)])
    memory = ConversationMemory()
    outcome = await make_loop(llm, recorder, audit).run(ctx(), memory, 1, "loop forever", "system")
    assert outcome.stopped == "limit"
    assert outcome.text is None
    assert len(recorder.calls) == 5
    assert memory.history(1) == [], "an unfinished exchange must not be kept"


async def test_llm_outage_is_reported_not_raised() -> None:
    outcome = await make_loop(ScriptedLLM(UNAVAILABLE), Recorder(), []).run(
        ctx(), ConversationMemory(), 1, "x", "system"
    )
    assert outcome.stopped == "llm_error"
    assert outcome.text is None


async def test_total_budget_is_enforced() -> None:
    loop = make_loop(SlowLLM(5), Recorder(), [], budget_seconds=0.2)
    started = time.monotonic()
    outcome = await loop.run(ctx(), ConversationMemory(), 1, "x", "system")
    assert outcome.stopped == "llm_error"
    assert time.monotonic() - started < 1.0


async def test_tool_failure_becomes_an_error_result() -> None:
    audit: list[AuditEntry] = []
    llm = ScriptedLLM(call_turn(("echo", {"word": "hi"})), text_turn("problem"))
    outcome = await make_loop(llm, Recorder(fail=True), audit).run(
        ctx(), ConversationMemory(), 1, "x", "system"
    )
    assert outcome.text == "problem"
    results = llm.transcripts[1][2]
    assert isinstance(results, ToolResults)
    assert results.results[0][1].code == ResultCode.ERROR
    assert "exploded" not in repr(results.results[0][1].data), "internal errors must not reach the LLM"
    assert audit[0].result == "ERROR"


async def test_completed_exchange_is_remembered_for_the_next_message() -> None:
    memory = ConversationMemory()
    llm = ScriptedLLM(call_turn(("echo", {"word": "hi"})), text_turn("first"), text_turn("second"))
    loop = make_loop(llm, Recorder(), [])
    await loop.run(ctx(), memory, 1, "one", "system")
    await loop.run(ctx(), memory, 1, "two", "system")
    third_call = llm.transcripts[2]
    assert [type(item).__name__ for item in third_call] == [
        "UserText", "ModelTurn", "ToolResults", "ModelTurn", "UserText",
    ]  # fmt: skip


async def test_empty_model_reply_is_not_sent() -> None:
    outcome = await make_loop(ScriptedLLM(text_turn("   ")), Recorder(), []).run(
        ctx(), ConversationMemory(), 1, "x", "system"
    )
    assert outcome.stopped == "llm_error"


async def test_tool_failure_log_contains_no_exception_message(capsys: pytest.CaptureFixture[str]) -> None:
    from clinic.observability import configure_logging

    configure_logging("INFO")
    llm = ScriptedLLM(call_turn(("echo", {"word": "hi"})), text_turn("problem"))
    await make_loop(llm, Recorder(fail=True), []).run(ctx(), ConversationMemory(), 1, "x", "system")
    output = capsys.readouterr().out
    assert "tool_failed" in output
    assert "exploded" not in output


class SlowTool:
    async def __call__(self, ctx: ToolContext, args: EchoArgs) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(ResultCode.OK, {})


async def test_budget_also_covers_tool_execution() -> None:
    registry = ToolRegistry([ToolSpec("echo", "Echo a word.", EchoArgs, SlowTool())])

    async def write(entry: AuditEntry) -> None:
        return None

    loop = AgentLoop(
        ScriptedLLM(call_turn(("echo", {"word": "hi"}))), registry, write, actor_id="t", budget_seconds=0.3
    )
    started = time.monotonic()
    outcome = await loop.run(ctx(), ConversationMemory(), 1, "x", "system")
    assert outcome.stopped == "llm_error"
    assert time.monotonic() - started < 1.5


async def test_audit_failure_does_not_lose_the_reply() -> None:
    async def failing_audit(entry: AuditEntry) -> None:
        raise ConnectionError("audit database unreachable")

    registry = ToolRegistry([ToolSpec("echo", "Echo a word.", EchoArgs, Recorder())])
    llm = ScriptedLLM(call_turn(("echo", {"word": "hi"})), text_turn("You said hi"))
    outcome = await AgentLoop(llm, registry, failing_audit, actor_id="t").run(
        ctx(), ConversationMemory(), 1, "x", "s"
    )
    assert (outcome.stopped, outcome.text) == ("reply", "You said hi")


async def test_invented_argument_names_never_reach_the_audit_log() -> None:
    audit: list[AuditEntry] = []
    invented = {"word": "hi", "I have chest pain since Monday": 1}
    llm = ScriptedLLM(call_turn(("echo", invented)), text_turn("ok"))
    await make_loop(llm, Recorder(), audit).run(ctx(), ConversationMemory(), 1, "x", "system")
    assert audit[0].result == "INVALID_ARGS"
    assert "chest pain" not in repr(audit[0].args)
    assert audit[0].args == {"invalid_fields": [], "unexpected_fields": 1}
