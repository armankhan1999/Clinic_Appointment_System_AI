"""Memory window, tool JSON schemas, system prompt (D-16) and the Gemini message mapping."""

import uuid
from datetime import date, time
from typing import Any
from zoneinfo import ZoneInfo

from google.genai import types

from clinic.agent.llm import ModelText, ModelTurn, ToolCall, ToolResults, UserText, to_gemini_contents
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
