"""Live smoke test against the real Gemini API with synthetic data only (D-16). Run: pytest -m live."""

import uuid

import pytest

from clinic.agent.llm import GeminiLLM
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import ListDoctorsArgs, ToolContext, ToolRegistry, ToolResult, ToolSpec
from clinic.config import get_settings
from clinic.domain.results import ResultCode

pytestmark = pytest.mark.live


async def fake_directory(ctx: ToolContext, args: ListDoctorsArgs) -> ToolResult:
    doctors = [
        {
            "doctor_id": "d1",
            "name": "Dr. Kavya Rao",
            "specialty": "Dermatologist",
            "working_days": ["Tuesday"],
        }
    ]
    if args.specialty and "derm" not in args.specialty.lower() and "skin" not in args.specialty.lower():
        return ToolResult(ResultCode.NO_MATCH, {"doctors": []})
    return ToolResult(ResultCode.OK, {"doctors": doctors})


async def test_gemini_calls_list_doctors_and_answers_from_the_result() -> None:
    settings = get_settings()
    llm = GeminiLLM(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
    audit: list[AuditEntry] = []

    async def write(entry: AuditEntry) -> None:
        audit.append(entry)

    registry = ToolRegistry(
        [ToolSpec("list_doctors", "List the clinic's doctors.", ListDoctorsArgs, fake_directory)]
    )
    loop = AgentLoop(llm, registry, write, actor_id=settings.gemini_model, budget_seconds=20)
    ctx = ToolContext(uuid.uuid4(), "live-1")
    outcome = await loop.run(
        ctx, ConversationMemory(), 1, "Which skin doctors do you have?", "Use the tools."
    )
    assert outcome.stopped == "reply", outcome
    assert [e.action for e in audit] == ["list_doctors"]
    assert outcome.text is not None
    assert "Kavya" in outcome.text
