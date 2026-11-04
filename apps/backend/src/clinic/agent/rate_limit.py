"""Per-user message rate limit (E7-S3-AC1). In memory: the MVP runs one bot process (GAP-26)."""

import time
from collections import deque
from collections.abc import Callable
from typing import Literal

type Verdict = Literal["ok", "warn", "drop"]


class RateLimiter:
    """More than `max_messages` in `window_s` → one "slow down" notice, then silence for `mute_s`."""

    def __init__(
        self,
        *,
        max_messages: int = 20,
        window_s: float = 60.0,
        mute_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_messages
        self._window = window_s
        self._mute = mute_s
        self._clock = clock
        self._recent: dict[int | str, deque[float]] = {}
        self._muted_until: dict[int | str, float] = {}

    def check(self, user_id: int | str) -> Verdict:
        now = self._clock()
        self._prune_idle(now)
        if self._muted_until.get(user_id, 0.0) > now:
            return "drop"
        self._muted_until.pop(user_id, None)
        recent = self._recent.setdefault(user_id, deque())
        while recent and now - recent[0] >= self._window:
            recent.popleft()
        recent.append(now)
        if len(recent) > self._max:
            recent.clear()
            self._muted_until[user_id] = now + self._mute
            return "warn"
        return "ok"

    def _prune_idle(self, now: float) -> None:
        idle_after = max(self._window, self._mute)
        for user_id in [u for u, times in self._recent.items() if not times or now - times[-1] > idle_after]:
            if self._muted_until.get(user_id, 0.0) <= now:
                self._recent.pop(user_id, None)
                self._muted_until.pop(user_id, None)

    def user_count(self) -> int:
        return len(self._recent)
