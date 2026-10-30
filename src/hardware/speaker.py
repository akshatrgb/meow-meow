"""Speaker helpers. Actual playback lives in :mod:`src.voice.audio_player`;
this module only inspects the ALSA playback devices (MAX98357A via I2S)."""

from __future__ import annotations

import shutil
import subprocess


def list_playback_devices() -> str:
    """Output of ``aplay -l`` for diagnostics (empty string if unavailable)."""
    if shutil.which("aplay") is None:
        return ""
    result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5, check=False)
    return (result.stdout or result.stderr).strip()
