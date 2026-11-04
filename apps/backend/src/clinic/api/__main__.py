"""`uv run clinic-api [--reload]`: serve the staff API on localhost only (the dashboard proxies to it).

`--reload` restarts the server when backend code changes (live development); it is refused in production.
"""

import argparse
from pathlib import Path
from typing import Any

import uvicorn

from clinic.config import Settings, get_settings
from clinic.observability import configure_logging

HOST = "127.0.0.1"
SOURCE_DIR = Path(__file__).resolve().parents[1]  # src/clinic


def serve_options(settings: Settings, *, reload: bool) -> dict[str, Any]:
    if reload and settings.env == "production":
        raise SystemExit("--reload is for development only; refusing it with ENV=production")
    options: dict[str, Any] = {
        "factory": True,
        "host": HOST,
        "port": settings.api_port,
        # access_log is off: the request middleware logs method, path, status and latency, no query strings.
        "access_log": False,
        "log_config": None,
        "reload": reload,
    }
    if reload:
        options["reload_dirs"] = [str(SOURCE_DIR)]
    return options


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="clinic-api", description="Serve the staff API on 127.0.0.1.")
    parser.add_argument(
        "--reload", action="store_true", help="restart when backend code changes (development)"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run("clinic.api.app:create_app", **serve_options(settings, reload=args.reload))


if __name__ == "__main__":
    main()
