"""Telegram adapter: Reply → Bot API markup, and which chats the bot serves."""

import pytest
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatType

from clinic.bot.telegram_app import serves_chat, to_markup
from clinic.conversation.replies import Button, Reply


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
