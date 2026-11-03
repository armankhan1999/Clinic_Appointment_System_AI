"""Transport-agnostic reply model. The Telegram adapter and the evaluation suite both consume it."""

from dataclasses import dataclass

CALLBACK_PREFIX = "v1"
MAX_CALLBACK_BYTES = 64  # Telegram Bot API limit for callback_data


@dataclass(frozen=True)
class IncomingUser:
    telegram_user_id: int


@dataclass(frozen=True)
class Button:
    text: str
    callback_data: str | None = None
    request_contact: bool = False

    def __post_init__(self) -> None:
        if self.callback_data is not None and len(self.callback_data.encode()) > MAX_CALLBACK_BYTES:
            raise ValueError("callback_data exceeds Telegram's 64-byte limit")


@dataclass(frozen=True)
class Reply:
    text: str
    inline_buttons: tuple[tuple[Button, ...], ...] = ()
    contact_button: Button | None = None
    remove_keyboard: bool = False


def callback(kind: str, value: str) -> str:
    return f"{CALLBACK_PREFIX}:{kind}:{value}"
