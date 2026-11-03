"""In-memory state is bounded by idle time (NFR-07: active conversations only; review finding 5)."""

from datetime import UTC, datetime, timedelta

from clinic.agent.llm import ModelText, UserText
from clinic.agent.memory import ConversationMemory, SessionTracker
from clinic.conversation.registration import RegistrationStore, Step


class Clock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


class WallClock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 7, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_registration_ttl_counts_from_the_last_activity() -> None:
    clock = WallClock()
    store = RegistrationStore(clock)
    store.start(1)
    clock.now += timedelta(minutes=50)
    state = store.get(1)
    assert state is not None
    state.step = Step.NAME
    clock.now += timedelta(minutes=50)  # 100 minutes after start, 50 after the last activity
    assert store.get(1) is not None


def test_abandoned_registrations_are_pruned_when_others_start() -> None:
    clock = WallClock()
    store = RegistrationStore(clock)
    store.start(1)
    store.start(2)
    clock.now += timedelta(hours=2)
    store.start(3)
    assert len(store) == 1, "phone numbers of abandoned flows must not stay in memory"


def test_memory_forgets_an_idle_conversation() -> None:
    clock = Clock()
    memory = ConversationMemory(idle_ttl_seconds=7200, clock=clock)
    memory.append(1, [UserText("hi"), ModelText("hello")])
    clock.seconds = 7199
    assert memory.history(1) != []
    memory.append(1, [UserText("again"), ModelText("sure")])
    clock.seconds = 7199 + 7201
    assert memory.history(1) == []
    assert not memory.has_history(1)


def test_memory_prunes_other_idle_users_on_write() -> None:
    clock = Clock()
    memory = ConversationMemory(idle_ttl_seconds=60, clock=clock)
    for user in range(5):
        memory.append(user, [UserText("hi"), ModelText("hello")])
    clock.seconds = 120
    memory.append(99, [UserText("hi"), ModelText("hello")])
    assert memory.user_count() == 1


def test_session_tracker_starts_a_new_session_after_idle_time() -> None:
    clock = Clock()
    sessions = SessionTracker(idle_ttl_seconds=7200, clock=clock)
    assert sessions.is_new_session(1) is True
    clock.seconds = 3600
    assert sessions.is_new_session(1) is False
    clock.seconds = 3600 + 7201
    assert sessions.is_new_session(1) is True


def test_session_tracker_prunes_idle_users() -> None:
    clock = Clock()
    sessions = SessionTracker(idle_ttl_seconds=60, clock=clock)
    for user in range(5):
        sessions.is_new_session(user)
    clock.seconds = 120
    sessions.is_new_session(99)
    assert sessions.user_count() == 1


def test_forget_clears_memory_and_session() -> None:
    clock = Clock()
    memory = ConversationMemory(clock=clock)
    memory.append(1, [UserText("hi"), ModelText("hello")])
    memory.clear(1)
    assert memory.history(1) == []
