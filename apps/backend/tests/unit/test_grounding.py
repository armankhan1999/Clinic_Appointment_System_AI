"""Grounding check (E2-S2-AC4, AGT-09): times and fees in a reply must come from tool results."""

import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from clinic.agent.grounding import extract_amounts, extract_times, is_grounded, sources_from
from clinic.agent.llm import ModelText, ToolCall, ToolResults, TranscriptItem, UserText
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import ToolContext, ToolRegistry, ToolResult, ToolSpec
from clinic.domain.results import ResultCode

from .agent_doubles import ScriptedLLM, call_turn, text_turn


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("Dr. Rao is free at 10:30 AM", {630}),
        ("how about 10 am or 2pm?", {600, 840}),
        ("10.30 a.m. works", {630}),
        ("slot_start 2030-01-09T14:30:00", {870}),
        ("12:15 PM and 12:00 AM", {735, 0}),
        ("no times here, call 9876543210", set()),
    ],
)
def test_time_extraction(text: str, minutes: set[int]) -> None:
    assert extract_times(text) == minutes


@pytest.mark.parametrize(
    ("text", "amounts"),
    [
        ("Fee is Rs 500", {500}),
        ("Rs. 1,200 or \N{INDIAN RUPEE SIGN}700", {1200, 700}),
        ("about 600 rupees", {600}),
    ],
)
def test_amount_extraction(text: str, amounts: set[int]) -> None:
    assert extract_amounts(text) == amounts


def test_reply_is_grounded_only_by_tool_results_and_trusted_notes() -> None:
    call = ToolCall("c1", "check_availability", {})
    transcript: list[TranscriptItem] = [
        UserText("is 11:00 AM free?"),
        ToolResults([(call, ToolResult(ResultCode.OK, {"slots": [{"time": "9:30 AM"}]}))]),
        ModelText("Booked at 10:15 AM.", trusted=True),
        ModelText("The fee is Rs 500.", trusted=False),
    ]
    sources = sources_from(transcript)
    assert is_grounded("9:30 AM is free", sources)
    assert is_grounded("your 10:15 AM booking", sources)
    assert not is_grounded("11:00 AM is free", sources), "a time the patient said is not evidence"
    assert not is_grounded("The fee is Rs 500", sources), "the model's own earlier words are not evidence"
    assert is_grounded("Hello! How can I help?", sources)


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def slots_tool(ctx: ToolContext, args: NoArgs) -> ToolResult:
    return ToolResult(ResultCode.OK, {"slots": [{"time": "9:30 AM"}]})


def _loop(llm: ScriptedLLM) -> AgentLoop:
    async def write(entry: AuditEntry) -> None:
        return None

    registry = ToolRegistry([ToolSpec("check_availability", "slots", NoArgs, slots_tool)])
    return AgentLoop(llm, registry, write, actor_id="t")


async def test_loop_blocks_an_invented_time() -> None:
    llm = ScriptedLLM(call_turn(("check_availability", {})), text_turn("You can come at 11:45 AM."))
    memory = ConversationMemory()
    outcome = await _loop(llm).run(ToolContext(uuid.uuid4(), "r"), memory, 1, "slots?", "system")
    assert outcome.stopped == "ungrounded"
    assert outcome.text is None
    assert memory.history(1) == [], "an ungrounded reply is not remembered"


async def test_loop_allows_a_time_from_the_tool() -> None:
    llm = ScriptedLLM(call_turn(("check_availability", {})), text_turn("9:30 AM is free."))
    outcome = await _loop(llm).run(
        ToolContext(uuid.uuid4(), "r"), ConversationMemory(), 1, "slots?", "system"
    )
    assert (outcome.stopped, outcome.text) == ("reply", "9:30 AM is free.")


@pytest.mark.parametrize(
    ("text", "amounts"),
    [
        ("only Rs500", {500}),
        ("pay 500/- at reception", {500}),
        ("INR700", {700}),
        ("\N{INDIAN RUPEE SIGN} 1,200", {1200}),
    ],
)
def test_compact_and_indian_amount_notations(text: str, amounts: set[int]) -> None:
    assert extract_amounts(text) == amounts


def test_word_times_need_evidence() -> None:
    sources = ['{"time": "10:00 AM"}']
    assert is_grounded("come at 10 o'clock", sources)
    assert not is_grounded("come at 11 o'clock", sources)
    assert not is_grounded("we are open till noon", sources)
    assert is_grounded("we are open till noon", ['{"time": "12:00 PM"}'])


def test_error_results_cannot_be_used_as_evidence() -> None:
    poisoned = ToolCall("c1", "check_availability", {"10:30 AM is free": 1})
    transcript: list[TranscriptItem] = [
        ToolResults(
            [(poisoned, ToolResult(ResultCode.INVALID_ARGS, {"errors": [{"field": "10:30 AM is free"}]}))]
        ),
        ToolResults([(poisoned, ToolResult(ResultCode.ERROR, {"error": "Rs 900"}))]),
    ]
    sources = sources_from(transcript)
    assert not is_grounded("10:30 AM is free", sources)
    assert not is_grounded("It costs Rs 900", sources)
