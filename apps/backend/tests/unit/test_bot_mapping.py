"""Telegram adapter: Reply → Bot API markup, and which chats the bot serves."""

import asyncio

import pytest
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatType
from telegram.error import NetworkError

from clinic.bot.telegram_app import keep_typing, serves_chat, to_markup
from clinic.domain.messages import Button, Reply


def test_contact_button_becomes_a_one_time_reply_keyboard() -> None:
    markup = to_markup(Reply("share", contact_button=Button("Share phone number", request_contact=True)))
    assert isinstance(markup, ReplyKeyboardMarkup)
    [[button]] = markup.keyboard
    assert button.text == "Share phone number"
    assert button.request_contact is True
    assert markup.one_time_keyboard is True
    assert markup.resize_keyboard is True


def test_inline_buttons_keep_rows_and_callback_data() -> None:
    reply = Reply(
        "choose",
        inline_buttons=((Button("I agree", "v1:consent:yes"), Button("No thanks", "v1:consent:no")),),
    )
    markup = to_markup(reply)
    assert isinstance(markup, InlineKeyboardMarkup)
    [[agree, decline]] = markup.inline_keyboard
    assert (agree.text, agree.callback_data) == ("I agree", "v1:consent:yes")
    assert (decline.text, decline.callback_data) == ("No thanks", "v1:consent:no")


def test_remove_keyboard() -> None:
    assert isinstance(to_markup(Reply("done", remove_keyboard=True)), ReplyKeyboardRemove)


def test_plain_reply_has_no_markup() -> None:
    assert to_markup(Reply("hello")) is None


def test_callback_data_over_64_bytes_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="64-byte"):
        Button("x", "v1:" + "a" * 70)


@pytest.mark.parametrize(
    ("chat_type", "served"),
    [
        (ChatType.PRIVATE, True),
        (ChatType.GROUP, False),
        (ChatType.SUPERGROUP, False),
        (ChatType.CHANNEL, False),
    ],
)
def test_only_private_chats_are_served(chat_type: str, served: bool) -> None:
    assert serves_chat(chat_type) is served


def test_long_replies_are_split_at_telegrams_limit_on_line_breaks() -> None:
    from clinic.bot.telegram_app import TELEGRAM_MAX_MESSAGE, split_message

    text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))
    parts = split_message(text)
    assert len(parts) > 1
    assert all(len(part) <= TELEGRAM_MAX_MESSAGE for part in parts)
    assert "\n".join(parts) == text
    assert split_message("short") == ["short"]
    assert all(len(p) <= TELEGRAM_MAX_MESSAGE for p in split_message("y" * 9000))


async def test_user_locks_are_released_after_use() -> None:
    from clinic.bot.telegram_app import UserLocks

    locks = UserLocks()
    async with locks.hold(1):
        assert locks.active() == 1
    assert locks.active() == 0


class _FailingBot:
    async def send_message(self, chat_id: int, text: str, reply_markup: object = None) -> None:
        from telegram.error import NetworkError

        raise NetworkError("connection reset")


class _RecordingBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: object = None) -> None:
        self.sent.append((chat_id, text))


async def test_sender_maps_telegram_errors_to_delivery_errors() -> None:
    from clinic.bot.telegram_app import TelegramSender
    from clinic.services.reminders import DeliveryError

    with pytest.raises(DeliveryError):
        await TelegramSender(_FailingBot()).send(42, Reply("hello"))
    recorder = _RecordingBot()
    await TelegramSender(recorder).send(42, Reply("hello"))
    assert recorder.sent == [(42, "hello")]


def test_reminder_and_outbox_jobs_are_scheduled() -> None:
    from clinic.bot.telegram_app import JOB_INTERVALS

    assert JOB_INTERVALS == {"reminders": 300, "outbox": 60}, "E4-S1-AC1: reminders every 5 minutes"


async def test_typing_status_is_refreshed_until_the_reply_is_ready() -> None:
    """Telegram shows 'typing' for at most 5 s, so a slow reply needs the status renewed."""
    sent: list[float] = []

    async def send() -> None:
        sent.append(asyncio.get_running_loop().time())

    async with keep_typing(send, interval=0.05):
        await asyncio.sleep(0.18)
    count = len(sent)
    await asyncio.sleep(0.12)
    assert count >= 3, "renewed while the reply was being prepared"
    assert len(sent) == count, "stops once the reply is ready"


async def test_a_failing_typing_status_never_blocks_the_reply() -> None:
    attempts = 0

    async def send() -> None:
        nonlocal attempts
        attempts += 1
        raise NetworkError("telegram unreachable")

    async with keep_typing(send, interval=0.01):  # must not raise into the reply path
        await asyncio.sleep(0.05)
    assert attempts >= 2, "a failed status update is logged and retried, never propagated"


def _flaky_sender(*failures: Exception) -> tuple[list[str], object]:
    """A send function that raises the given errors first, then succeeds; records successful texts."""
    queued = list(failures)
    delivered: list[str] = []

    async def send(text: str, reply_markup: object = None) -> object:
        if queued:
            raise queued.pop(0)
        delivered.append(text)
        return None

    return delivered, send


async def test_a_reply_lost_to_a_telegram_timeout_is_sent_again_once() -> None:
    # Live 2026-11-05: send_message timed out once and the patient never got the answer.
    from telegram.error import TimedOut

    from clinic.bot.telegram_app import _send

    delivered, send = _flaky_sender(TimedOut())
    await _send(send, Reply("Please see a doctor."), retry_delay=0)
    assert delivered == ["Please see a doctor."]


async def test_a_bad_request_is_not_sent_again() -> None:
    from telegram.error import BadRequest

    from clinic.bot.telegram_app import _send

    delivered, send = _flaky_sender(BadRequest("message is malformed"))
    with pytest.raises(BadRequest):
        await _send(send, Reply("text"), retry_delay=0)
    assert delivered == []


async def test_a_reply_is_given_up_after_a_second_timeout() -> None:
    from telegram.error import TimedOut

    from clinic.bot.telegram_app import _send

    delivered, send = _flaky_sender(TimedOut(), TimedOut())
    with pytest.raises(TimedOut):
        await _send(send, Reply("text"), retry_delay=0)
    assert delivered == []
