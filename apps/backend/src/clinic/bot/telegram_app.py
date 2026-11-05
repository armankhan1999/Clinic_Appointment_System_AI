"""Telegram adapter (python-telegram-bot, long polling, D-18). No business rules live here."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, Protocol

import structlog
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    ExtBot,
    JobQueue,
    MessageHandler,
    filters,
)

from clinic.conversation.service import ConversationService
from clinic.domain.messages import IncomingUser, Reply
from clinic.observability import safe_exception_fields
from clinic.services.notifications import NotificationService
from clinic.services.reminders import DeliveryError, ReminderService

log = structlog.get_logger(__name__)

type Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None
type BotApplication = Application[
    ExtBot[None],
    ContextTypes.DEFAULT_TYPE,
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
    JobQueue[ContextTypes.DEFAULT_TYPE],
]


def serves_chat(chat_type: str) -> bool:
    """Contact sharing only works in private chats, and patient data must never reach a group."""
    return chat_type == ChatType.PRIVATE


def to_markup(reply: Reply) -> Markup:
    if reply.contact_button is not None:
        button = KeyboardButton(reply.contact_button.text, request_contact=True)
        return ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)
    if reply.inline_buttons:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(b.text, callback_data=b.callback_data) for b in row]
                for row in reply.inline_buttons
            ]
        )
    if reply.remove_keyboard:
        return ReplyKeyboardRemove()
    return None


TELEGRAM_MAX_MESSAGE = 4096  # Bot API limit for a text message


def split_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE) -> list[str]:
    """Split on line breaks where possible, hard-splitting any single line longer than the limit."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts


class UserLocks:
    """One update at a time per user (consistent registration state and memory) while different users are
    served concurrently. A lock is dropped once nobody holds or waits for it, so the map stays bounded."""

    def __init__(self) -> None:
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, user_id: int) -> AsyncIterator[None]:
        lock, users = self._locks.get(user_id, (asyncio.Lock(), 0))
        self._locks[user_id] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[user_id]
            if users <= 1:
                del self._locks[user_id]
            else:
                self._locks[user_id] = (lock, users - 1)

    def active(self) -> int:
        return len(self._locks)


type Sender = Callable[..., Coroutine[Any, Any, object]]


async def _send(send: Sender, reply: Reply, *, retry_delay: float = 1.0) -> None:
    """Send one reply; a network failure (not a malformed request) gets one more try.

    A reply can follow up to a minute of work, so losing it to one network blip is worse than the rare
    duplicate when the first attempt did reach Telegram but its answer timed out.
    """
    chunks = split_message(reply.text)
    for index, chunk in enumerate(chunks):
        markup = to_markup(reply) if index == len(chunks) - 1 else None
        try:
            await send(chunk, reply_markup=markup)
        except BadRequest:
            raise
        except NetworkError as exc:
            log.warning("reply_send_retry", error=type(exc).__name__)
            await asyncio.sleep(retry_delay)
            await send(chunk, reply_markup=markup)


class _SendsMessages(Protocol):
    async def send_message(self, chat_id: int, text: str, *, reply_markup: Markup = None) -> object: ...


class TelegramSender:
    """MessageSender for the reminder and outbox jobs; every Telegram failure becomes a DeliveryError."""

    def __init__(self, bot: _SendsMessages) -> None:
        self._bot = bot

    async def send(self, chat_id: int, reply: Reply) -> None:
        async def send_text(text: str, reply_markup: Markup = None) -> object:
            return await self._bot.send_message(chat_id, text, reply_markup=reply_markup)

        try:
            await _send(send_text, reply)
        except TelegramError as exc:
            raise DeliveryError(type(exc).__name__) from exc


JOB_INTERVALS = {"reminders": 300, "outbox": 60}  # seconds; E4-S1-AC1: the reminder job runs every 5 minutes


def schedule_jobs(
    application: BotApplication, reminders: ReminderService, notifications: NotificationService
) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        raise RuntimeError("python-telegram-bot was installed without the job-queue extra")

    async def run_reminders(_: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await reminders.run_once()
        except Exception as exc:  # one bad run must not stop the scheduler; logged
            log.error("reminder_job_failed", **safe_exception_fields(exc))
        log.info("scheduler_heartbeat", job="reminders")

    async def run_outbox(_: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await notifications.drain()
        except Exception as exc:  # one bad run must not stop the scheduler; logged
            log.error("outbox_job_failed", **safe_exception_fields(exc))

    job_queue.run_repeating(run_reminders, interval=JOB_INTERVALS["reminders"], first=15, name="reminders")
    job_queue.run_repeating(run_outbox, interval=JOB_INTERVALS["outbox"], first=20, name="outbox")


TYPING_REFRESH_S = 4.0  # Telegram shows "typing" for 5 s or less per call (Bot.send_chat_action)


@asynccontextmanager
async def keep_typing(
    send: Callable[[], Coroutine[Any, Any, object]], interval: float = TYPING_REFRESH_S
) -> AsyncIterator[None]:
    """Shows "typing..." while a reply is prepared; a failed status update never delays or blocks it."""

    async def renew() -> None:
        while True:
            try:
                await send()
            except TelegramError as exc:
                log.info("typing_status_failed", error=type(exc).__name__)
            await asyncio.sleep(interval)

    task = asyncio.create_task(renew())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class TelegramAdapter:
    def __init__(self, conversation: ConversationService) -> None:
        self._conversation = conversation
        self._locks = UserLocks()

    async def on_text(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or message.text is None:
            return
        async with (
            self._locks.hold(user.id),
            keep_typing(lambda: message.reply_chat_action(ChatAction.TYPING)),
        ):
            replies = await self._conversation.handle_text(IncomingUser(user.id), message.text)
        for reply in replies:
            await _send(message.reply_text, reply)

    async def on_contact(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or message.contact is None:
            return
        async with self._locks.hold(user.id):
            replies = await self._conversation.handle_contact(
                IncomingUser(user.id),
                contact_user_id=message.contact.user_id,
                phone=message.contact.phone_number,
            )
        for reply in replies:
            await _send(message.reply_text, reply)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat = update.effective_chat
        if query is None or chat is None or not serves_chat(chat.type):
            return
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)  # one tap per button set
        except BadRequest as exc:
            log.info("callback_markup_not_removed", error=exc.message)
        async with self._locks.hold(query.from_user.id):
            replies = await self._conversation.handle_callback(
                IncomingUser(query.from_user.id), query.data or ""
            )

        async def send(text: str, reply_markup: Markup = None) -> object:
            return await context.bot.send_message(chat.id, text, reply_markup=reply_markup)

        for reply in replies:
            await _send(send, reply)

    async def on_error(self, _: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.error is not None:
            log.error("telegram_handler_error", **safe_exception_fields(context.error))


def build_application(
    token: str,
    conversation: ConversationService,
    *,
    on_shutdown: Callable[[BotApplication], Coroutine[Any, Any, None]],
) -> BotApplication:
    adapter = TelegramAdapter(conversation)
    application = (
        ApplicationBuilder().token(token).concurrent_updates(True).post_shutdown(on_shutdown).build()
    )
    private_messages = filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE
    application.add_handler(MessageHandler(private_messages & filters.CONTACT, adapter.on_contact))
    application.add_handler(MessageHandler(private_messages & filters.TEXT, adapter.on_text))
    application.add_handler(CallbackQueryHandler(adapter.on_callback))
    application.add_error_handler(adapter.on_error)
    return application
