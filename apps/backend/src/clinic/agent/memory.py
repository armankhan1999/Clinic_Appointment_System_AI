"""Per-user conversation state, in process memory only (NFR-07, D-07, IMP-13).

Everything here is forgotten after `idle_ttl_seconds` without activity, and idle users are pruned on
write, so personal context never outlives an active conversation and memory stays bounded.
"""

import time
from collections import deque
from collections.abc import Callable

from clinic.agent.llm import TranscriptItem

DEFAULT_IDLE_TTL_SECONDS = 2 * 60 * 60


class ConversationMemory:
    """The last `max_exchanges` exchanges per user: one patient message plus the model's tool steps and reply.

    Ten exchanges hold the last 20 patient and assistant messages (AGT memory rule). Whole exchanges are
    kept so that a function call is never separated from its result.
    """

    def __init__(
        self,
        max_exchanges: int = 10,
        *,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_exchanges
        self._ttl = idle_ttl_seconds
        self._clock = clock
        self._exchanges: dict[int, deque[list[TranscriptItem]]] = {}
        self._last_active: dict[int, float] = {}

    def _expired(self, key: int, now: float) -> bool:
        return now - self._last_active.get(key, now) > self._ttl

    def history(self, key: int) -> list[TranscriptItem]:
        if self._expired(key, self._clock()):
            self.clear(key)
        return [item for exchange in self._exchanges.get(key, ()) for item in exchange]

    def append(self, key: int, exchange: list[TranscriptItem]) -> None:
        now = self._clock()
        for idle in [user for user in self._last_active if self._expired(user, now)]:
            self.clear(idle)
        self._exchanges.setdefault(key, deque(maxlen=self._max)).append(list(exchange))
        self._last_active[key] = now

    def has_history(self, key: int) -> bool:
        return bool(self.history(key))

    def clear(self, key: int) -> None:
        self._exchanges.pop(key, None)
        self._last_active.pop(key, None)

    def user_count(self) -> int:
        return len(self._exchanges)


class SessionTracker:
    """A session starts with the first message after `idle_ttl_seconds` of silence (GAP-37 greeting rule)."""

    def __init__(
        self,
        *,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = idle_ttl_seconds
        self._clock = clock
        self._last_seen: dict[int, float] = {}

    def is_new_session(self, key: int) -> bool:
        now = self._clock()
        for idle in [
            user for user, seen in self._last_seen.items() if now - seen > self._ttl and user != key
        ]:
            del self._last_seen[idle]
        previous = self._last_seen.get(key)
        self._last_seen[key] = now
        return previous is None or now - previous > self._ttl

    def mark_seen(self, key: int) -> None:
        self._last_seen[key] = self._clock()

    def forget(self, key: int) -> None:
        self._last_seen.pop(key, None)

    def user_count(self) -> int:
        return len(self._last_seen)
