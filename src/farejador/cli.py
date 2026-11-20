# Filename: cli.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Command line entry point: ``farejador run | check-config | healthcheck | version``."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Sequence

from farejador import __version__
from farejador.app import Runtime, build_runtime
from farejador.config import ConfigError, Mode, Settings
from farejador.github.errors import AuthError, GitHubApiError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2

RuntimeBuilder = Callable[[Settings], Awaitable[Runtime]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="farejador", description="Agentic first-pass reviewer for GitHub pull requests."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="start the service")
    run.add_argument(
        "--mode",
        choices=[mode.value for mode in Mode],
        help="polling, webhook or both (overrides FAREJADOR_MODE)",
    )

    commands.add_parser("check-config", help="validate the configuration and exit")

    health = commands.add_parser("healthcheck", help="exit 0 when the service looks healthy")
    health.add_argument("--timeout", type=float, default=3.0)

    commands.add_parser("version", help="print the version")
    return parser


def main(argv: Sequence[str] | None = None, *, builder: RuntimeBuilder = build_runtime) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        print(__version__)
        return EXIT_OK
    if args.command == "healthcheck":
        return _healthcheck(args.timeout)
    if args.command == "run" and args.mode:
        os.environ["FAREJADOR_MODE"] = args.mode

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG
    if args.command == "check-config":
        print(f"Configuration OK (mode={settings.mode.value}, model={settings.model})")
        return EXIT_OK
    return _run(settings, builder)


def _run(settings: Settings, builder: RuntimeBuilder) -> int:
    async def start() -> None:
        runtime = await builder(settings)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        await runtime.run(stop)

    try:
        asyncio.run(start())
    except (GitHubApiError, AuthError) as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"Could not start: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _healthcheck(timeout: float) -> int:
    """Used by Docker: only the webhook modes have something to probe."""
    mode = os.environ.get("FAREJADOR_MODE", Mode.POLLING.value)
    if mode == Mode.POLLING.value:
        return EXIT_OK
    port = os.environ.get("FAREJADOR_PORT", "8080")
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=timeout
        ) as response:
            return EXIT_OK if response.status == 200 else EXIT_ERROR
    except (urllib.error.URLError, OSError, ValueError):
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
