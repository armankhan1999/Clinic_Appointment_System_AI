"""Telegram adapter (python-telegram-bot, long polling, D-18). No business rules live here."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest
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

from clinic.conversation.replies import IncomingUser, Reply
from clinic.conversation.service import ConversationService
from clinic.observability import safe_exception_fields

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


class TelegramAdapter:
    def __init__(self, conversation: ConversationService) -> None:
        self._conversation = conversation
        # One update at a time per user keeps registration state and memory consistent, while
        # different users are served concurrently.
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def on_text(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or message.text is None:
            return
        async with self._lock(user.id):
            replies = await self._conversation.handle_text(IncomingUser(user.id), message.text)
        for reply in replies:
            await message.reply_text(reply.text, reply_markup=to_markup(reply))

    async def on_contact(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or message.contact is None:
            return
        async with self._lock(user.id):
            replies = await self._conversation.handle_contact(
                IncomingUser(user.id),
                contact_user_id=message.contact.user_id,
                phone=message.contact.phone_number,
            )
        for reply in replies:
            await message.reply_text(reply.text, reply_markup=to_markup(reply))

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
        async with self._lock(query.from_user.id):
            replies = await self._conversation.handle_callback(
                IncomingUser(query.from_user.id), query.data or ""
            )
        for reply in replies:
            await context.bot.send_message(chat.id, reply.text, reply_markup=to_markup(reply))

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
