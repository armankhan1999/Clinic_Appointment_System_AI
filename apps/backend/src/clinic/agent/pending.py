"""Pending confirmations (AGT-11): one per user, single use, expiring, in memory only (D-07, GAP-17).

A write is staged here and executed only when the same user taps Confirm with the matching token, so a
restart, a stale button or another user's tap can never write anything.
"""

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

type PendingKind = Literal["book", "reschedule", "cancel", "delete_data"]

DEFAULT_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class PendingAction:
    token: str
    kind: PendingKind
    params: Mapping[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None


class PendingStore:
    def __init__(self, clock: Callable[[], datetime], *, ttl: timedelta = DEFAULT_TTL) -> None:
        self._clock = clock
        self._ttl = ttl
        self._actions: dict[int, PendingAction] = {}

    def __len__(self) -> int:
        return len(self._actions)

    def put(self, user_id: int, kind: PendingKind, params: Mapping[str, Any]) -> PendingAction:
        now = self._clock()
        expired = [
            uid for uid, action in self._actions.items() if action.expires_at and action.expires_at < now
        ]
        for uid in expired:
            del self._actions[uid]
        action = PendingAction(secrets.token_urlsafe(9), kind, dict(params), now + self._ttl)
        self._actions[user_id] = action  # one pending action per user: a new one replaces the old
        return action

    def pop(self, user_id: int, token: str) -> PendingAction | None:
        action = self._actions.get(user_id)
        if action is None or not secrets.compare_digest(action.token, token):
            return None
        del self._actions[user_id]
        if action.expires_at is not None and action.expires_at < self._clock():
            return None
        return action

    def peek(self, user_id: int) -> PendingAction | None:
        return self._actions.get(user_id)

    def discard(self, user_id: int) -> None:
        self._actions.pop(user_id, None)
