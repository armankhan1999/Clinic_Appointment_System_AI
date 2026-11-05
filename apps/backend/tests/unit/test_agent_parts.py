"""Memory window, tool JSON schemas, system prompt (D-16) and the Gemini message mapping."""

import asyncio
import uuid
from datetime import date, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from google.genai import types
from pydantic import SecretStr

from clinic.agent.llm import (
    GeminiLLM,
    LlmUnavailableError,
    ModelText,
    ModelTurn,
    ToolCall,
    ToolResults,
    UserText,
    to_gemini_contents,
)
from clinic.agent.memory import ConversationMemory
from clinic.agent.prompt import build_system_prompt
from clinic.agent.tools import ListDoctorsArgs, ToolResult, tool_json_schema
from clinic.domain.results import ResultCode
from clinic.services.clinic_settings import ClinicSettingsView

from .agent_doubles import text_turn

VIEW = ClinicSettingsView(
    clinic_name="Demo Family Clinic",
    phone="+12025550100",
    address="12 Example Road",
    staff_hours_text="Mon-Sat 9-6",
    tz=ZoneInfo("Asia/Kolkata"),
    emergency_number="112",
    emergency_phrases=("chest pain",),
    cutoff_minutes=120,
    booking_window_days=30,
    max_upcoming_per_patient=3,
    max_per_doctor_per_day=1,
    morning_end=time(12),
    afternoon_end=time(17),
)


def test_memory_keeps_the_last_ten_exchanges_per_user() -> None:
    memory = ConversationMemory(max_exchanges=10)
    for i in range(12):
        memory.append(1, [UserText(f"q{i}"), ModelText(f"a{i}")])
    memory.append(2, [UserText("other"), ModelText("user")])
    history = memory.history(1)
    assert len(history) == 20
    assert history[0] == UserText("q2")
    assert memory.history(2) == [UserText("other"), ModelText("user")]
    memory.clear(1)
    assert memory.history(1) == []
    assert memory.has_history(2)


def test_tool_schema_forbids_extra_fields_and_flattens_optionals() -> None:
    schema = tool_json_schema(ListDoctorsArgs)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    specialty: dict[str, Any] = schema["properties"]["specialty"]
    assert specialty["type"] == "string"
    assert specialty["maxLength"] == 40
    assert "anyOf" not in specialty
    assert "title" not in schema
    assert "title" not in specialty
    assert schema.get("required", []) == []


def test_system_prompt_states_scope_and_contains_no_patient_data() -> None:
    prompt = build_system_prompt(VIEW, date(2030, 1, 9))
    assert "Demo Family Clinic" in prompt
    assert "Wednesday, 9 January 2030" in prompt
    assert "Asia/Kolkata" in prompt
    for rule in ("medical advice", "tool", "never an instruction", "Confirm"):
        assert rule in prompt
    for personal in ("+1202555", "telegram", "Asha"):
        assert personal.lower() not in prompt.lower().replace(VIEW.phone.lower(), "")


def test_gemini_mapping_replays_raw_model_turns_verbatim() -> None:
    raw = types.Content(role="model", parts=[types.Part(text="kept as is", thought_signature=b"sig")])
    call = ToolCall(id="c1", name="list_doctors", args={})
    contents = to_gemini_contents(
        [
            UserText("hello"),
            ModelText("earlier answer"),
            ModelTurn(text_turn("ignored").__class__(text=None, tool_calls=[call], raw=raw)),
            ToolResults([(call, ToolResult(ResultCode.OK, {"doctors": []}))]),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "model", "user"]
    assert contents[2] is raw
    parts = contents[3].parts
    assert parts is not None
    response = parts[0].function_response
    assert response is not None
    assert (response.id, response.name) == ("c1", "list_doctors")
    assert response.response == {"code": "OK", "data": {"doctors": []}}


def test_tool_result_payload_shape() -> None:
    assert ToolResult(ResultCode.NO_MATCH, {"doctors": []}).payload() == {
        "code": "NO_MATCH",
        "data": {"doctors": []},
    }
    assert uuid.UUID(int=1)


def test_schema_keeps_arguments_named_like_schema_keywords() -> None:
    from pydantic import BaseModel, ConfigDict

    class Awkward(BaseModel):
        model_config = ConfigDict(extra="forbid")
        title: str
        default: int | None = None

    schema = tool_json_schema(Awkward)
    assert set(schema["properties"]) == {"title", "default"}
    assert schema["required"] == ["title"]
    assert "title" not in schema["properties"]["title"]
    assert schema["properties"]["default"]["type"] == "integer"


async def test_gemini_client_can_be_closed_without_a_network_call() -> None:
    llm = GeminiLLM(SecretStr("not-a-real-key"), "gemini-3.5-flash-lite", 8.0)
    await llm.aclose()  # releases the HTTP client's sockets (no request is made)


def _gemini_with_responses(statuses: list[int]) -> tuple[GeminiLLM, list[int], httpx.AsyncClient]:
    """A real GeminiLLM whose HTTP layer answers with the given statuses in order (no network)."""
    seen: list[int] = []

    def answer(request: httpx.Request) -> httpx.Response:
        status = statuses[min(len(seen), len(statuses) - 1)]
        seen.append(status)
        if status == 200:
            body = {
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": "OK"}]}, "finishReason": "STOP"}
                ]
            }
            return httpx.Response(200, json=body)
        return httpx.Response(
            status, json={"error": {"code": status, "message": "provider error", "status": "X"}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    llm = GeminiLLM(SecretStr("not-a-real-key"), "gemini-3.5-flash-lite", 8.0, http_client=client)
    return llm, seen, client


async def test_a_temporary_provider_error_is_retried_once() -> None:
    # Live 2026-11-05: Gemini answered 503 twice in four minutes and each turn fell back to "can't answer".
    llm, seen, client = _gemini_with_responses([503, 200])
    turn = await llm.generate(system="rules", transcript=[UserText("hello")], tools=[])
    assert (turn.text, seen) == ("OK", [503, 200])
    await client.aclose()


async def test_quota_errors_are_not_retried() -> None:
    llm, seen, client = _gemini_with_responses([429, 200])
    with pytest.raises(LlmUnavailableError):
        await llm.generate(system="rules", transcript=[UserText("hello")], tools=[])
    assert seen == [429], "a used-up daily quota does not recover within the call budget"
    await client.aclose()


async def test_a_provider_that_stays_down_is_given_up_after_one_retry() -> None:
    llm, seen, client = _gemini_with_responses([503, 503, 503])
    with pytest.raises(LlmUnavailableError):
        await llm.generate(system="rules", transcript=[UserText("hello")], tools=[])
    assert seen == [503, 503]
    await client.aclose()


async def test_one_model_call_is_cut_off_at_the_per_call_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """E1-S1-AC3 with the split budget: a provider that never answers fails one call within its timeout.

    Only the third-party SDK call is replaced; the timeout handling under test is GeminiLLM's own.
    """
    llm = GeminiLLM(SecretStr("not-a-real-key"), "gemini-3.5-flash-lite", 0.05)

    async def never_answers(**_: object) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(llm._client.aio.models, "generate_content", never_answers)
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(LlmUnavailableError):
        await llm.generate(system="rules", transcript=[UserText("hello")], tools=[])
    assert loop.time() - started < 1.0
    await llm.aclose()
