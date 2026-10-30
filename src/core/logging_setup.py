"""Logging with automatic secret redaction and a size-capped log file."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Iterable


class SecretFilter(logging.Filter):
    """Replaces any known secret value found in a log record with ``***``."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            for secret in self._secrets:
                message = message.replace(secret, "***")
            record.msg, record.args = message, None
        return True


def setup_logging(level: str, log_file: Path | None, secrets: Iterable[str] = ()) -> None:
    """Configure root logging to stderr and (optionally) a rotating file."""
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    redact = SecretFilter(secrets)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.handlers.RotatingFileHandler(
                log_file, maxBytes=512_000, backupCount=2, encoding="utf-8"))
        except OSError as error:
            print(f"Warning: cannot write log file {log_file}: {error}")
    for handler in handlers:
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        root.addHandler(handler)
    # `requests`/`urllib3` DEBUG output can include URLs; keep them quiet.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
