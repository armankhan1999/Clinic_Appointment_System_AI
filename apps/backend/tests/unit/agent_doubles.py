"""Test doubles for the LLM adapter: the external dependency, never the loop under test."""

import asyncio
from collections.abc import Sequence
from typing import Any

from clinic.agent.llm import LlmTurn, LlmUnavailableError, ToolCall, TranscriptItem
from clinic.agent.tools import ToolSpec


class ScriptedLLM:
    """Returns scripted turns in order and records every transcript it was given."""

    def __init__(self, *turns: LlmTurn | Exception) -> None:
        self._turns = list(turns)
        self.transcripts: list[list[TranscriptItem]] = []
        self.systems: list[str] = []

    async def generate(
        self, *, system: str, transcript: Sequence[TranscriptItem], tools: Sequence[ToolSpec[Any]]
    ) -> LlmTurn:
        self.systems.append(system)
        self.transcripts.append(list(transcript))
        turn = self._turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


class SlowLLM:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    async def generate(
        self, *, system: str, transcript: Sequence[TranscriptItem], tools: Sequence[ToolSpec[Any]]
    ) -> LlmTurn:
        await asyncio.sleep(self.seconds)
        return text_turn("too late")


def text_turn(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], raw=None)


def call_turn(*calls: tuple[str, dict[str, Any]]) -> LlmTurn:
    return LlmTurn(
        text=None,
        tool_calls=[ToolCall(id=f"call-{i}", name=name, args=args) for i, (name, args) in enumerate(calls)],
        raw=None,
    )


UNAVAILABLE = LlmUnavailableError("simulated outage")
