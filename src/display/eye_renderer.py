"""Draws the eyes. Needs Pillow; everything else about the face is data.

Frames are drawn 2x oversampled in 8-bit grayscale and downscaled for smooth
edges, then coloured by the display device using :mod:`src.display.palette`.
Replace this class to change the look without touching any AI logic.
"""

from __future__ import annotations

from src.display.animations import EyeState
from src.display.palette import EYE_LEVEL

SUPERSAMPLE = 2
HIGHLIGHT_LEVEL = 255


class EyeRenderer:
    def __init__(self, size: int = 240, eye_gap: float = 96.0) -> None:
        from PIL import Image, ImageDraw  # imported lazily: optional on machines without display

        self._Image, self._ImageDraw = Image, ImageDraw
        self.size = size
        self._eye_gap = eye_gap  # distance between eye centres at 240px
        self._scale = size / 240.0

    def render(self, s: EyeState):
        """Return a ``size`` x ``size`` mode "L" image for ``s``."""
        k = SUPERSAMPLE * self._scale
        big = self._Image.new("L", (int(240 * k), int(240 * k)), 0)
        draw = self._ImageDraw.Draw(big)
        body = int(EYE_LEVEL * s.brightness)
        spark = int(HIGHLIGHT_LEVEL * max(s.brightness, 0.4))
        cy = 120 + s.bob_y + s.gaze_y
        for side, (cx, scale) in enumerate((
            (120 - self._eye_gap / 2 + s.gaze_x, s.left_scale),
            (120 + self._eye_gap / 2 + s.gaze_x, s.right_scale),
        )):
            self._draw_eye(draw, s, cx, cy, scale * s.pulse, side == 1, k, body, spark)
        small = big.resize((self.size, self.size), self._Image.BOX)
        return small

    def _draw_eye(self, d, s: EyeState, cx: float, cy: float, scale: float, right: bool,
                  k: float, body: int, spark: int) -> None:
        w = s.width * scale
        h = max(4.0, s.height * scale * (1.0 - 0.93 * s.blink))
        x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2

        def px(*values: float) -> list[float]:
            return [v * k for v in values]

        if s.shape == "heart":
            self._draw_heart(d, cx, cy, w, h, k, body, spark, s.blink)
            return

        radius = min(w, h) / 2 * s.radius
        d.rounded_rectangle(px(x0, y0, x1, y1), radius=radius * k, fill=body)
        if s.blink < 0.3:  # sparkle highlight, hidden while the eye is closing
            r = max(2.0, w * 0.09)
            hx, hy = x0 + w * 0.3, y0 + h * 0.28
            d.ellipse(px(hx - r, hy - r, hx + r, hy + r), fill=spark)

        # upper lid (also gives slanted sad/annoyed brows)
        slant = s.lid_slant * (s.slant_right_mult if right else 1.0)
        inner_cover = h * (s.lid_top - 0.4 * slant)
        outer_cover = h * (s.lid_top + 0.4 * slant)
        if s.lid_top > 0.001 or abs(slant) > 0.001:
            left_y, right_y = (outer_cover, inner_cover) if not right else (inner_cover, outer_cover)
            d.polygon(px(x0 - 2, y0 - 2, x1 + 2, y0 - 2, x1 + 2, y0 + right_y, x0 - 2, y0 + left_y), fill=0)

        # rising lower curve: turns the eye into a happy "^"
        if s.cheek > 0.01:
            top = y1 - s.cheek * h
            d.ellipse(px(cx - 0.75 * w, top, cx + 0.75 * w, top + 1.6 * h), fill=0)

    @staticmethod
    def _draw_heart(d, cx, cy, w, h, k, body, spark, blink) -> None:
        s = min(w, h) * 0.5 * (1.0 - 0.5 * blink)
        r = 0.5 * s
        for dx in (-0.5 * s, 0.5 * s):
            d.ellipse([(cx + dx - r) * k, (cy - 0.25 * s - r) * k, (cx + dx + r) * k, (cy - 0.25 * s + r) * k],
                      fill=body)
        d.polygon([(cx - 0.97 * s) * k, (cy - 0.05 * s) * k, (cx + 0.97 * s) * k, (cy - 0.05 * s) * k,
                   cx * k, (cy + 0.95 * s) * k], fill=body)
        hr = max(2.0, s * 0.14)
        d.ellipse([(cx - 0.55 * s - hr) * k, (cy - 0.4 * s - hr) * k,
                   (cx - 0.55 * s + hr) * k, (cy - 0.4 * s + hr) * k], fill=spark)
