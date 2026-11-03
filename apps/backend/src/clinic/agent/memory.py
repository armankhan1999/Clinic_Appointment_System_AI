"""Per-user conversation memory, in process memory only (NFR-07, D-07, IMP-13)."""

from collections import deque

from clinic.agent.llm import TranscriptItem


class ConversationMemory:
    """Keeps the last `max_exchanges` exchanges (one patient message plus the model's tool steps and reply).

    Ten exchanges hold the last 20 patient and assistant messages (AGT memory rule). Whole exchanges are
    kept so that a function call is never separated from its result.
    """

    def __init__(self, max_exchanges: int = 10) -> None:
        self._max = max_exchanges
        self._exchanges: dict[int, deque[list[TranscriptItem]]] = {}

    def history(self, key: int) -> list[TranscriptItem]:
        return [item for exchange in self._exchanges.get(key, ()) for item in exchange]

    def append(self, key: int, exchange: list[TranscriptItem]) -> None:
        self._exchanges.setdefault(key, deque(maxlen=self._max)).append(list(exchange))

    def has_history(self, key: int) -> bool:
        return bool(self._exchanges.get(key))

    def clear(self, key: int) -> None:
        self._exchanges.pop(key, None)
