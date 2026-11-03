"""`uv run clinic-bot`: the patient Telegram bot, long polling (D-18)."""

import structlog
from telegram import Update

from clinic.bot.telegram_app import BotApplication, build_application
from clinic.config import get_settings
from clinic.observability import configure_logging
from clinic.runtime import build_bot_runtime

log = structlog.get_logger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    runtime = build_bot_runtime(settings)

    async def shutdown(_: BotApplication) -> None:
        await runtime.close()
        log.info("bot_stopped")

    application = build_application(
        settings.telegram_bot_token.get_secret_value(), runtime.conversation, on_shutdown=shutdown
    )
    log.info("bot_starting", mode="long_polling", model=settings.gemini_model)
    application.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])


if __name__ == "__main__":
    main()
