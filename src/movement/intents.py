"""Parse explicit movement commands out of spoken/typed text.

Deliberately strict: the whole utterance must be a short command, so ordinary
conversation ("I can't stop thinking about it") never moves the robot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.movement.motor_controller import Direction

_PREFIX = r"^(?:hey\s+)?(?:meow meow[,\s]+)?(?:please\s+)?(?:can you\s+)?"
_SUFFIX = r"(?:\s+(?:please|now|a little|a bit))*$"
_SECONDS = r"(?:\s+for\s+(?P<secs>\d+(?:\.\d+)?)\s+seconds?)?"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_PREFIX + r"(?:go |move |drive )?(?:forward|forwards|ahead)" + _SECONDS + _SUFFIX, re.I), "forward"),
    (re.compile(_PREFIX + r"(?:go |move |drive )?(?:backward|backwards|back|reverse)" + _SECONDS + _SUFFIX, re.I), "backward"),
    (re.compile(_PREFIX + r"turn (?:to the )?left" + _SECONDS + _SUFFIX, re.I), "left"),
    (re.compile(_PREFIX + r"turn (?:to the )?right" + _SECONDS + _SUFFIX, re.I), "right"),
    (re.compile(_PREFIX + r"emergency stop" + _SUFFIX, re.I), "estop"),
    (re.compile(_PREFIX + r"(?:stop|halt|freeze)(?: moving)?" + _SUFFIX, re.I), "stop"),
    (re.compile(_PREFIX + r"(?:enable|arm|start) (?:movement|moving|motors)" + _SUFFIX, re.I), "arm"),
    (re.compile(_PREFIX + r"(?:disable|disarm) (?:movement|moving|motors)" + _SUFFIX, re.I), "disarm"),
]


@dataclass(frozen=True)
class MoveIntent:
    action: str  # forward | backward | left | right | stop | estop | arm | disarm
    duration_s: float | None = None

    @property
    def direction(self) -> Direction | None:
        try:
            return Direction(self.action)
        except ValueError:
            return None


def parse_movement(text: str) -> MoveIntent | None:
    """Return a :class:`MoveIntent` if ``text`` is exactly a movement command."""
    cleaned = text.strip().rstrip(".!?")
    if not cleaned or len(cleaned.split()) > 9:
        return None
    for pattern, action in _PATTERNS:
        if m := pattern.match(cleaned):
            secs = m.groupdict().get("secs")
            return MoveIntent(action, float(secs) if secs else None)
    return None
