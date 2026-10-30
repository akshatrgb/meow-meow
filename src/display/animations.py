"""Animation logic: smooth transitions, blinking, idle eye movement.

Pure math -- no drawing and no hardware -- so it is cheap to run and easy to test.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields

from src.display.expressions import EXPRESSIONS, Expression, EyeParams

_SMOOTH_FIELDS = ("width", "height", "radius", "lid_top", "lid_slant", "slant_right_mult", "cheek",
                  "left_scale", "right_scale", "brightness")
_GAZE_MAX_X = 12.0  # px
_GAZE_MAX_Y = 10.0


@dataclass(frozen=True)
class EyeState:
    """Everything the renderer needs for one frame."""

    width: float
    height: float
    radius: float
    lid_top: float
    lid_slant: float
    slant_right_mult: float
    cheek: float
    left_scale: float
    right_scale: float
    brightness: float
    gaze_x: float   # px offset
    gaze_y: float   # px offset
    blink: float    # 0 open .. 1 closed
    bob_y: float    # px
    pulse: float    # size multiplier
    shape: str

    def key(self) -> tuple:
        """Rounded values; equal keys mean the frame would look identical."""
        return tuple(round(getattr(self, f.name), 2) if isinstance(getattr(self, f.name), float)
                     else getattr(self, f.name) for f in fields(self))


class Animator:
    """Moves the eyes toward the current expression and adds life-like motion."""

    def __init__(self, rng: random.Random | None = None, speed: float = 9.0,
                 gaze_speed: float = 14.0) -> None:
        self._rng = rng or random.Random()
        self._speed = speed
        self._gaze_speed = gaze_speed
        self._t = 0.0
        self.expression = Expression.NORMAL
        target = EXPRESSIONS[self.expression]
        self._cur = {name: float(getattr(target, name)) for name in _SMOOTH_FIELDS}
        self._shape = target.shape
        self._gaze = [0.0, 0.0]
        self._saccade = (0.0, 0.0)
        self._next_saccade = self._rng.uniform(1.0, 3.0)
        self._blink_start = -1.0
        self._blink_len = 0.2
        self._next_blink = self._rng.uniform(2.0, 5.0)

    def set_expression(self, expression: Expression) -> None:
        if expression != self.expression:
            self.expression = expression
            self._shape = EXPRESSIONS[expression].shape

    def blink_now(self) -> None:
        self._blink_start, self._blink_len = self._t, 0.2

    def update(self, dt: float) -> EyeState:
        """Advance by ``dt`` seconds and return the state to draw."""
        dt = max(0.0, min(dt, 0.5))
        self._t += dt
        t = self._t
        target: EyeParams = EXPRESSIONS[self.expression]

        k = 1.0 - math.exp(-self._speed * dt)
        for name in _SMOOTH_FIELDS:
            self._cur[name] += (float(getattr(target, name)) - self._cur[name]) * k

        # --- gaze: random glances, except THINKING which drifts slowly
        if self.expression is Expression.THINKING:
            want_x = target.gaze_x + 0.2 * math.sin(t * 0.8)
            want_y = target.gaze_y + 0.15 * math.cos(t * 1.1)
        else:
            if t >= self._next_saccade:
                self._saccade = (self._rng.uniform(-0.5, 0.5), self._rng.uniform(-0.3, 0.3))
                self._next_saccade = t + self._rng.uniform(1.2, 3.5)
            want_x, want_y = target.gaze_x + self._saccade[0], target.gaze_y + self._saccade[1]
        kg = 1.0 - math.exp(-self._gaze_speed * dt)
        self._gaze[0] += (max(-1, min(1, want_x)) - self._gaze[0]) * kg
        self._gaze[1] += (max(-1, min(1, want_y)) - self._gaze[1]) * kg

        # --- blinking
        sleepy = self.expression in (Expression.SLEEPY, Expression.OFFLINE)
        if self._blink_start < 0 and t >= self._next_blink:
            self._blink_start = t
            self._blink_len = 0.45 if sleepy else 0.2
            self._next_blink = t + (self._rng.uniform(1.5, 3.0) if sleepy else self._rng.uniform(2.5, 6.0))
            if not sleepy and self._rng.random() < 0.15:  # occasional double blink
                self._next_blink = t + self._blink_len + 0.15
        blink = 0.0
        if self._blink_start >= 0:
            progress = (t - self._blink_start) / self._blink_len
            if progress >= 1.0:
                self._blink_start = -1.0
            else:
                blink = math.sin(math.pi * progress)

        # --- expression-specific idle motion
        bob = 4.0 * math.sin(t * 9.0) if self.expression is Expression.EXCITED else 0.0
        pulse = 1.0 + 0.06 * math.sin(t * 5.0) if self.expression is Expression.LOVE else 1.0
        lid_extra = 0.05 * math.sin(t * 0.8) if self.expression is Expression.SLEEPY else 0.0

        c = self._cur
        return EyeState(
            width=c["width"], height=c["height"], radius=c["radius"],
            lid_top=max(0.0, min(0.95, c["lid_top"] + lid_extra)),
            lid_slant=c["lid_slant"], slant_right_mult=c["slant_right_mult"], cheek=c["cheek"],
            left_scale=c["left_scale"], right_scale=c["right_scale"], brightness=c["brightness"],
            gaze_x=self._gaze[0] * _GAZE_MAX_X, gaze_y=self._gaze[1] * _GAZE_MAX_Y,
            blink=blink, bob_y=bob, pulse=pulse, shape=self._shape,
        )
