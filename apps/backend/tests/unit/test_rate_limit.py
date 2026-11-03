"""Message rate limit (E7-S3-AC1, GAP-26): 20 per minute, one slow-down notice, then 60 s of silence."""

from clinic.agent.rate_limit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


def test_twenty_messages_a_minute_are_allowed() -> None:
    limiter = RateLimiter(clock=Clock())
    assert [limiter.check(1) for _ in range(20)] == ["ok"] * 20


def test_the_21st_message_warns_once_then_messages_are_dropped_for_60_seconds() -> None:
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(20):
        limiter.check(1)
    assert limiter.check(1) == "warn"
    assert limiter.check(1) == "drop"
    clock.seconds += 59
    assert limiter.check(1) == "drop"
    clock.seconds += 2
    assert limiter.check(1) == "ok"


def test_the_window_slides() -> None:
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(20):
        limiter.check(1)
        clock.seconds += 3.1  # 20 messages over 62 s
    assert limiter.check(1) == "ok"


def test_users_are_limited_independently_and_idle_ones_are_pruned() -> None:
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(21):
        limiter.check(1)
    assert limiter.check(2) == "ok"
    clock.seconds += 600
    limiter.check(3)
    assert limiter.user_count() == 1
