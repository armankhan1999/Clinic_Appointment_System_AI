"""`uv run clinic-api`: serve the staff API on localhost only (the dashboard reaches it same-origin)."""

import uvicorn

from clinic.config import get_settings
from clinic.observability import configure_logging

HOST = "127.0.0.1"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    # access_log is off: the request middleware logs method, path, status and latency without query strings.
    uvicorn.run(
        "clinic.api.app:create_app",
        factory=True,
        host=HOST,
        port=settings.api_port,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
