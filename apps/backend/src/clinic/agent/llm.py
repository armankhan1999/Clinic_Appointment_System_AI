"""LLM adapter boundary: a provider-neutral transcript plus the Gemini implementation (D-03, D-16).

Gemini 3 models attach thought signatures to function-call turns and reject a follow-up request
whose history drops them (verified 2026-11-03: HTTP 400 "Function call is missing a
thought_signature"). Model turns are therefore replayed from the provider's raw content.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import SecretStr

if TYPE_CHECKING:
    from clinic.agent.tools import ToolResult, ToolSpec

log = structlog.get_logger(__name__)


class LlmUnavailableError(Exception):
    """The model could not produce a usable turn (outage, timeout, quota, blocked or empty response)."""


@dataclass(frozen=True)
class ToolCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class LlmTurn:
    text: str | None
    tool_calls: list[ToolCall]
    raw: object = field(default=None, compare=False, repr=False)  # provider message, replayed verbatim


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class ModelText:
    text: str
    trusted: bool = False  # written by code (e.g. a booking result), not by the model


@dataclass(frozen=True)
class ModelTurn:
    turn: LlmTurn


@dataclass(frozen=True)
class ToolResults:
    results: list[tuple[ToolCall, ToolResult]]


type TranscriptItem = UserText | ModelText | ModelTurn | ToolResults


class LLM(Protocol):
    async def generate(
        self, *, system: str, transcript: Sequence[TranscriptItem], tools: Sequence[ToolSpec[Any]]
    ) -> LlmTurn: ...


def _model_turn_content(turn: LlmTurn) -> types.Content:
    if isinstance(turn.raw, types.Content):
        return turn.raw
    parts = [
        types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.args))
        for c in turn.tool_calls
    ]
    if turn.text:
        parts.insert(0, types.Part.from_text(text=turn.text))
    return types.Content(role="model", parts=parts)


def to_gemini_contents(transcript: Sequence[TranscriptItem]) -> list[types.Content]:
    contents: list[types.Content] = []
    for item in transcript:
        match item:
            case UserText(text):
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
            case ModelText(text, _):
                contents.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
            case ModelTurn(turn):
                contents.append(_model_turn_content(turn))
            case ToolResults(results):
                parts = [
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.id, name=call.name, response=result.payload()
                        )
                    )
                    for call, result in results
                ]
                contents.append(types.Content(role="user", parts=parts))
    return contents


class GeminiLLM:
    def __init__(self, api_key: SecretStr, model: str, timeout_s: float) -> None:
        self._client = genai.Client(api_key=api_key.get_secret_value())
        self._model = model
        self._timeout_s = timeout_s

    @property
    def model(self) -> str:
        return self._model

    async def generate(
        self, *, system: str, transcript: Sequence[TranscriptItem], tools: Sequence[ToolSpec[Any]]
    ) -> LlmTurn:
        from clinic.agent.tools import tool_json_schema

        declarations = [
            types.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters_json_schema=tool_json_schema(spec.args_model),
            )
            for spec in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
            max_output_tokens=1024,
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                response = await self._client.aio.models.generate_content(
                    model=self._model, contents=to_gemini_contents(transcript), config=config
                )
        except (genai_errors.APIError, httpx.HTTPError, TimeoutError, OSError) as exc:
            status = getattr(exc, "code", None)
            log.warning("llm_unavailable", provider="gemini", error=type(exc).__name__, status=status)
            raise LlmUnavailableError(type(exc).__name__) from exc
        candidates = response.candidates or []
        content = candidates[0].content if candidates else None
        if content is None or not content.parts:
            log.warning("llm_empty_response", provider="gemini")
            raise LlmUnavailableError("empty response")
        calls = [
            ToolCall(id=c.id, name=c.name or "", args=dict(c.args or {}))
            for c in response.function_calls or []
        ]
        text = "".join(part.text for part in content.parts if part.text and not part.thought)
        return LlmTurn(text=text or None, tool_calls=calls, raw=content)
