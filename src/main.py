"""Meow Meow entry point:  python -m src.main  [--voice] [--mock-all] [--mock-llm]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from src.config.settings import ConfigError, Settings
from src.core.application import Application
from src.core.factory import build_components
from src.core.logging_setup import setup_logging
from src.hardware.gpio_manager import PinConflictError, build_pin_registry, format_pin_table

MOCK_HARDWARE = {
    "AUDIO_IN": "mock", "AUDIO_OUT": "mock", "DISPLAY": "mock", "MOTORS": "mock",
    "TTS_PROVIDER": "mock", "STT_PROVIDER": "mock",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="meow-meow", description="Meow Meow AI companion robot")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--voice", action="store_true", help="talk with the microphone (INPUT_MODE=voice)")
    mode.add_argument("--text", action="store_true", help="type instead of talking (INPUT_MODE=text)")
    p.add_argument("--mock-all", action="store_true", help="use mock audio, display, motors, TTS and STT")
    p.add_argument("--mock-llm", action="store_true", help="no API key needed; canned replies cycle emotions")
    p.add_argument("--check-config", action="store_true", help="validate configuration and exit")
    p.add_argument("--pins", action="store_true", help="print the GPIO wiring table and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    overrides: dict[str, str] = {}
    if args.mock_all:
        overrides.update(MOCK_HARDWARE)
    if args.voice:
        overrides["INPUT_MODE"] = "voice"
    if args.text:
        overrides["INPUT_MODE"] = "text"

    try:
        settings = Settings.from_env(environ={**os.environ, **overrides})
        registry = build_pin_registry(settings)
    except (ConfigError, PinConflictError) as error:
        print(f"Configuration problem:\n{error}", file=sys.stderr)
        return 2

    if args.pins:
        print(format_pin_table(registry))
        return 0

    problems = [] if args.mock_llm else settings.check_ready_for_conversation()
    if problems or args.check_config:
        for problem in problems:
            print(f"Configuration problem: {problem}", file=sys.stderr)
        if not problems:
            print("Configuration OK")
            for key, value in settings.redacted().items():
                print(f"  {key} = {value}")
        return 2 if problems else 0

    setup_logging(settings.log_level, settings.log_file, settings.secrets())
    log = logging.getLogger("meow")
    log.info("Starting with settings: %s", settings.redacted())

    app = Application(settings, build_components(settings, mock_llm=args.mock_llm))
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
