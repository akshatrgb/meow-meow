"""Component-by-component hardware tests.  Run from the project root:

    python -m scripts.hwtest pins
    python -m scripts.hwtest audio-devices
    python -m scripts.hwtest speaker
    python -m scripts.hwtest mic [--seconds 5]
    python -m scripts.hwtest tts "Hello, I am Meow Meow" [--list-voices]
    python -m scripts.hwtest stt
    python -m scripts.hwtest display [--seconds 2]
    python -m scripts.hwtest motors --i-confirm-wheels-lifted

Each test uses the same configuration as the robot (config/.env).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from src.config.settings import Settings
from src.hardware.gpio_manager import build_pin_registry, format_pin_table
from src.hardware.microphone import ArecordSource, AudioError, list_capture_devices
from src.hardware.speaker import list_playback_devices
from src.voice.audio_capture import CHUNK_MS, UtteranceDetector
from src.voice.audio_player import AplayPlayer, MockPlayer
from src.voice.audio_utils import apply_gain, make_tone_wav, pcm_to_wav, rms
from src.voice.svara_client import AudioClip, MockTTS, SvaraClient


def _player(s: Settings):
    return AplayPlayer(s.audio_out_device) if s.audio_out == "real" else MockPlayer()


def cmd_pins(s: Settings, args) -> int:
    print(format_pin_table(build_pin_registry(s)))
    print("\nNo conflicts found.")
    return 0


def cmd_audio_devices(s: Settings, args) -> int:
    print("== Capture devices (arecord -l) ==\n" + (list_capture_devices() or "arecord not available"))
    print("\n== Playback devices (aplay -l) ==\n" + (list_playback_devices() or "aplay not available"))
    print(f"\nConfigured: AUDIO_IN_DEVICE={s.audio_in_device}  AUDIO_OUT_DEVICE={s.audio_out_device}")
    return 0


def cmd_speaker(s: Settings, args) -> int:
    print(f"Playing a quiet 440 Hz tone for 2 s on '{s.audio_out_device}' (AUDIO_OUT={s.audio_out})...")
    asyncio.run(_player(s).play(AudioClip(make_tone_wav(2.0, 440, 16000, volume=0.2))))
    print("Did you hear a steady beep? If not, see docs/ASSEMBLY.md > Speaker troubleshooting.")
    return 0


async def _mic(s: Settings, seconds: float) -> int:
    if s.audio_in != "real":
        print("AUDIO_IN is mock here (no arecord). Run this on the Pi.")
        return 1
    source = ArecordSource(s.audio_in_device, s.sample_rate)
    chunk_bytes = int(s.sample_rate * CHUNK_MS / 1000) * 2
    detector = UtteranceDetector(s.sample_rate, min_rms=s.vad_min_rms, threshold_factor=s.vad_threshold_factor)
    levels: list[float] = []
    pcm = bytearray()
    print(f"Recording {seconds:.0f}s from '{s.audio_in_device}' (MIC_GAIN={s.mic_gain}). "
          "Stay quiet for 2 s, then speak.\n")
    await source.start()
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chunk = apply_gain(await source.read(chunk_bytes), s.mic_gain)
            pcm += chunk
            level = rms(chunk)
            levels.append(level)
            detector.feed(chunk)
            bar = "#" * min(60, int(level / 100))
            print(f"\r{level:7.0f} {bar:<60} thr={detector.threshold:6.0f}", end="", flush=True)
    finally:
        await source.stop()
    quiet, peak = sorted(levels)[len(levels) // 10], max(levels)
    print(f"\n\nquiet level ~{quiet:.0f}, peak {peak:.0f}")
    if peak < 200:
        print("Peak is very low: wiring/overlay problem, or raise MIC_GAIN (try 4-8).")
    elif peak < 3 * max(quiet, 1):
        print("Speech barely rises above the noise: raise MIC_GAIN or move closer.")
    else:
        print(f"Looks healthy. Suggested VAD_MIN_RMS ~ {max(100, int(quiet * 2.5))}.")
    wav_path = "logs/mic_test.wav"
    with open(wav_path, "wb") as f:
        f.write(pcm_to_wav(bytes(pcm), s.sample_rate))
    print(f"Saved {wav_path} (play it with: aplay {wav_path})")
    return 0


def cmd_mic(s: Settings, args) -> int:
    try:
        return asyncio.run(_mic(s, args.seconds))
    except AudioError as error:
        print(f"\nMicrophone error: {error}")
        return 1


def cmd_tts(s: Settings, args) -> int:
    if s.tts_provider == "svara":
        client = SvaraClient.from_settings(s)
        if args.list_voices:
            print(json.dumps(client.list_voices(), indent=2))
            return 0
        tts = client
    else:
        print("TTS_PROVIDER resolved to MOCK (set SVARA_API_KEY and SVARA_BASE_URL for real speech).")
        tts = MockTTS()
    text = args.text or "Hi! I'm Meow Meow, your little robot friend."
    started = time.monotonic()
    clip = asyncio.run(tts.synthesize(text))
    print(f"Generated {len(clip.data)} bytes in {time.monotonic() - started:.1f}s; playing...")
    asyncio.run(_player(s).play(clip))
    return 0


def cmd_stt(s: Settings, args) -> int:
    from dataclasses import replace

    from src.core.factory import build_listener

    s = replace(s, input_mode="voice")
    listener = build_listener(s)
    print("Say something...")
    text = asyncio.run(listener.listen())
    print(f"Heard: {text!r}" if text else "Heard nothing.")
    return 0


def cmd_display(s: Settings, args) -> int:
    import random

    from src.display.animations import Animator
    from src.display.eye_renderer import EyeRenderer
    from src.display.expressions import Expression
    from src.hardware.display_device import create_display_device

    device = create_display_device(s)
    renderer, anim = EyeRenderer(), Animator(random.Random(1))
    print(f"Display: {type(device).__name__}. Cycling expressions, {args.seconds}s each. Ctrl-C to stop.")
    try:
        for expression in Expression:
            print(f"  {expression.value}")
            anim.set_expression(expression)
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                device.show(renderer.render(anim.update(1 / 12)))
                time.sleep(1 / 12)
    except KeyboardInterrupt:
        pass
    finally:
        device.close()
    return 0


def cmd_motors(s: Settings, args) -> int:
    from dataclasses import replace

    from src.movement.motor_controller import Direction, MotorController

    if not args.i_confirm_wheels_lifted:
        print("Refusing to run: lift the robot so the wheels spin freely, keep a hand on the power switch,\n"
              "then re-run with --i-confirm-wheels-lifted")
        return 2
    s = replace(s, movement_enabled=True, motors="real" if s.motors == "real" or args.real else "mock")
    if s.motors != "real":
        print("Using MOCK motors. To drive the real ones set MOTORS=real in config/.env or pass --real.")

    async def run() -> None:
        controller = MotorController.from_settings(s)
        controller.safety.arm()
        try:
            for direction in Direction:
                print(f"  {direction.value} for 0.6 s")
                await controller.move(direction, speed=0.4, duration_s=0.6)
                await asyncio.sleep(1.2)
        finally:
            await controller.close()
            print("Motors stopped and released.")

    asyncio.run(run())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hwtest", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("pins")
    sub.add_parser("audio-devices")
    sub.add_parser("speaker")
    sub.add_parser("stt")
    m = sub.add_parser("mic"); m.add_argument("--seconds", type=float, default=6)
    t = sub.add_parser("tts"); t.add_argument("text", nargs="?"); t.add_argument("--list-voices", action="store_true")
    d = sub.add_parser("display"); d.add_argument("--seconds", type=float, default=2)
    mo = sub.add_parser("motors")
    mo.add_argument("--i-confirm-wheels-lifted", action="store_true")
    mo.add_argument("--real", action="store_true", help="drive the real motors")
    args = p.parse_args(argv)

    settings = Settings.from_env()
    handler = {"pins": cmd_pins, "audio-devices": cmd_audio_devices, "speaker": cmd_speaker, "mic": cmd_mic,
               "tts": cmd_tts, "stt": cmd_stt, "display": cmd_display, "motors": cmd_motors}[args.command]
    return handler(settings, args)


if __name__ == "__main__":
    sys.exit(main())
