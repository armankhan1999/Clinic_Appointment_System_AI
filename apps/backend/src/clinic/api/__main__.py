"""`uv run clinic-api`: serve the staff API on localhost only (the dashboard proxies to it).

After backend changes during development, restart it with `pwsh scripts/restart.ps1 -Part api`
(uvicorn's auto-reload stopped restarting its worker after the first reload on the dev PC).
"""

from typing import Any

import uvicorn

from clinic.config import Settings, get_settings
from clinic.observability import configure_logging

HOST = "127.0.0.1"
# Clients must close idle connections before the server does. The Next.js proxy (Node's global agent) idles
# sockets for 5 s, uvicorn's default; a typical load balancer idles 60 s. 65 s keeps the server last.
KEEP_ALIVE_SECONDS = 65


def serve_options(settings: Settings) -> dict[str, Any]:
    return {
        "factory": True,
        "host": HOST,
        "port": settings.api_port,
        # access_log is off: the request middleware logs method, path, status and latency, no query strings.
        "access_log": False,
        "log_config": None,
        "timeout_keep_alive": KEEP_ALIVE_SECONDS,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run("clinic.api.app:create_app", **serve_options(settings))


if __name__ == "__main__":
    main()
