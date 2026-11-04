"""Pending confirmations: one per user, single use, expiring (AGT-11, GAP-17, D-07)."""

from datetime import UTC, datetime, timedelta

from clinic.agent.pending import PendingStore
from clinic.domain.messages import MAX_CALLBACK_BYTES


class WallClock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 7, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_pop_returns_the_action_once() -> None:
    store = PendingStore(WallClock())
    action = store.put(1, "book", {"slot": "x"})
    assert store.pop(1, action.token) == action
    assert store.pop(1, action.token) is None


def test_a_new_action_replaces_the_previous_one() -> None:
    store = PendingStore(WallClock())
    old = store.put(1, "book", {})
    new = store.put(1, "delete_data", {})
    assert store.pop(1, old.token) is None
    assert store.pop(1, new.token) == new


def test_tokens_are_bound_to_their_user() -> None:
    store = PendingStore(WallClock())
    action = store.put(1, "book", {})
    assert store.pop(2, action.token) is None
    assert store.pop(1, action.token) == action


def test_expired_actions_cannot_be_confirmed_and_are_pruned() -> None:
    clock = WallClock()
    store = PendingStore(clock, ttl=timedelta(minutes=10))
    action = store.put(1, "book", {})
    store.put(2, "book", {})
    clock.now += timedelta(minutes=11)
    assert store.pop(1, action.token) is None
    store.put(3, "book", {})
    assert len(store) == 1


def test_callback_data_fits_telegram_limits() -> None:
    action = PendingStore(WallClock()).put(1, "book", {})
    assert len(f"v1:confirm:{action.token}".encode()) <= MAX_CALLBACK_BYTES
    assert action.token.isascii()


def test_a_completed_action_is_remembered_for_a_repeated_tap() -> None:
    """E3-S3-AC3: a second tap on a used button can be answered from what it already did."""
    clock = WallClock()
    store = PendingStore(clock, ttl=timedelta(minutes=10))
    action = store.put(1, "cancel", {"reference": "APT-000001"})
    assert store.pop(1, action.token) == action
    assert store.completed(1, action.token) is None, "popping alone does not count as done"
    store.remember_completed(1, action)
    assert store.completed(1, action.token) == action
    assert store.completed(2, action.token) is None, "bound to the user"
    assert store.completed(1, "another-token") is None
    clock.now += timedelta(minutes=11)
    assert store.completed(1, action.token) is None, "forgotten when the button would have expired"
