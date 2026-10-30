"""Expression definitions: *what* each face looks like, as plain data.

Nothing here draws anything. To restyle the robot, edit these numbers or swap
the renderer; the AI code only ever names an :class:`Expression`.

Units are pixels on a 240x240 canvas; ``lid_*`` and ``cheek`` are fractions of
the eye height; gaze is -1..1 (x: left..right, y: up..down).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.ai.personality import Emotion


class Expression(StrEnum):
    NORMAL = "normal"
    HAPPY = "happy"
    SAD = "sad"
    SLEEPY = "sleepy"
    EXCITED = "excited"
    CURIOUS = "curious"
    THINKING = "thinking"
    CONFUSED = "confused"
    LOVE = "love"
    OFFLINE = "offline"


@dataclass(frozen=True)
class EyeParams:
    """Target shape of the eyes for one expression."""

    width: float = 62.0
    height: float = 74.0
    radius: float = 0.9          # corner radius as a fraction of the shorter side / 2
    lid_top: float = 0.0         # fraction of the eye covered from the top
    lid_slant: float = 0.0       # >0 lowers the outer top corner (sad); <0 lowers the inner (annoyed)
    slant_right_mult: float = 1.0  # -1 mirrors the slant on the right eye (confused)
    cheek: float = 0.0           # fraction covered from the bottom by a curve (happy "^ ^")
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    left_scale: float = 1.0
    right_scale: float = 1.0
    brightness: float = 1.0
    shape: str = "round"         # "round" | "heart"


EXPRESSIONS: dict[Expression, EyeParams] = {
    Expression.NORMAL: EyeParams(),
    Expression.HAPPY: EyeParams(width=66, height=70, cheek=0.5),
    Expression.SAD: EyeParams(width=60, height=70, lid_top=0.12, lid_slant=0.9, gaze_y=0.5),
    Expression.SLEEPY: EyeParams(height=60, lid_top=0.55, gaze_y=0.3, brightness=0.8),
    Expression.EXCITED: EyeParams(width=70, height=86),
    Expression.CURIOUS: EyeParams(right_scale=1.25, gaze_x=0.5, gaze_y=-0.3),
    Expression.THINKING: EyeParams(width=58, height=66, lid_top=0.2, lid_slant=-0.3,
                                   gaze_x=0.7, gaze_y=-0.7),
    Expression.CONFUSED: EyeParams(width=60, height=68, lid_top=0.1, lid_slant=0.6,
                                   slant_right_mult=-1.0, left_scale=1.1, right_scale=0.85),
    Expression.LOVE: EyeParams(width=74, height=74, shape="heart"),
    Expression.OFFLINE: EyeParams(width=60, height=64, lid_top=0.35, lid_slant=0.8,
                                  gaze_y=0.6, brightness=0.35),
}

EMOTION_TO_EXPRESSION: dict[Emotion, Expression] = {
    Emotion.HAPPY: Expression.HAPPY,
    Emotion.EXCITED: Expression.EXCITED,
    Emotion.CURIOUS: Expression.CURIOUS,
    Emotion.SAD: Expression.SAD,
    Emotion.SLEEPY: Expression.SLEEPY,
    Emotion.THINKING: Expression.THINKING,
    Emotion.CONFUSED: Expression.CONFUSED,
    Emotion.LOVE: Expression.LOVE,
    Emotion.NEUTRAL: Expression.NORMAL,
}
