"""`uv run clinic-api`: serve the staff API on localhost only (the dashboard proxies to it).

After backend changes during development, restart it with `pwsh scripts/restart.ps1 -Part api`
(uvicorn's auto-reload stopped restarting its worker after the first reload on the dev PC).
"""

from typing import Any

import uvicorn

from clinic.config import Settings, get_settings
from clinic.observability import configure_logging

HOST = "127.0.0.1"


def serve_options(settings: Settings) -> dict[str, Any]:
    return {
        "factory": True,
        "host": HOST,
        "port": settings.api_port,
        # access_log is off: the request middleware logs method, path, status and latency, no query strings.
        "access_log": False,
        "log_config": None,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run("clinic.api.app:create_app", **serve_options(settings))


if __name__ == "__main__":
    main()
