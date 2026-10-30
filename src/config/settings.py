"""Environment-based configuration for Meow Meow.

Values come from ``config/.env`` (same location the project always used) and
real environment variables, which win over the file. Every problem found is
collected and reported together in a single :class:`ConfigError`.

Secrets are never part of ``repr()`` and :meth:`Settings.redacted` hides them.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "config" / ".env"


class ConfigError(ValueError):
    """Raised when configuration is invalid; lists every problem found."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(self.problems))


class _Reader:
    """Typed accessors over a mapping that accumulate problems instead of raising."""

    def __init__(self, values: Mapping[str, str | None]) -> None:
        self._values = values
        self.problems: list[str] = []

    def str(self, key: str, default: str = "") -> str:
        value = self._values.get(key)
        return default if value is None or not value.strip() else value.strip()

    def int(self, key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
        raw = self.str(key)
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            self.problems.append(f"{key} must be an integer (got {raw!r})")
            return default
        return self._bounded(key, value, lo, hi, default)

    def optional_int(self, key: str) -> int | None:
        raw = self.str(key)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            self.problems.append(f"{key} must be an integer (got {raw!r})")
            return None

    def float(self, key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
        raw = self.str(key)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            self.problems.append(f"{key} must be a number (got {raw!r})")
            return default
        return self._bounded(key, value, lo, hi, default)

    def bool(self, key: str, default: bool) -> bool:
        raw = self.str(key).lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        self.problems.append(f"{key} must be true or false (got {raw!r})")
        return default

    def choice(self, key: str, default: str, choices: Sequence[str]) -> str:
        raw = self.str(key, default).lower()
        if raw not in choices:
            self.problems.append(f"{key} must be one of {', '.join(choices)} (got {raw!r})")
            return default
        return raw

    def pin(self, key: str, default: int) -> int:
        return self.int(key, default, lo=0, hi=27)

    def color(self, key: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
        raw = self.str(key).lstrip("#")
        if not raw:
            return default
        try:
            if len(raw) != 6:
                raise ValueError
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        except ValueError:
            self.problems.append(f"{key} must be a hex colour like #35d0ff (got {raw!r})")
            return default

    def _bounded(self, key: str, value, lo, hi, default):
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            self.problems.append(f"{key} must be between {lo} and {hi} (got {value})")
            return default
        return value


def _auto(mode: str, real_available: bool) -> str:
    """Resolve an ``auto|real|mock`` setting to ``real`` or ``mock``."""
    if mode == "auto":
        return "real" if real_available else "mock"
    return mode


def _on_linux() -> bool:
    return platform.system() == "Linux"


@dataclass(frozen=True)
class Settings:
    """All runtime configuration. Build it with :meth:`Settings.from_env`."""

    # LLM
    llm_provider: str = "openrouter"
    openrouter_api_key: str = field(default="", repr=False)
    openrouter_model: str = "openai/gpt-4.1-mini"
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    llm_max_tokens: int = 200
    llm_temperature: float = 0.8
    llm_json_mode: bool = True
    history_token_budget: int = 1500
    history_max_messages: int = 24

    # TTS
    tts_provider: str = "mock"
    svara_api_key: str = field(default="", repr=False)
    svara_base_url: str = ""
    svara_voice: str = "en_female"
    svara_timeout_s: float = 30.0
    svara_emotion_tags: bool = False

    # Input / STT
    input_mode: str = "text"
    listen_timeout_s: float = 20.0
    barge_in: bool = False
    stt_provider: str = "mock"
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_api_key: str = field(default="", repr=False)
    stt_model: str = "whisper-large-v3-turbo"
    stt_language: str = "en"
    stt_timeout_s: float = 20.0

    # Audio devices
    audio_in: str = "mock"
    audio_out: str = "mock"
    audio_in_device: str = "default"
    audio_out_device: str = "default"
    mic_gain: float = 1.0
    sample_rate: int = 16000
    vad_min_rms: float = 300.0
    vad_threshold_factor: float = 3.0
    vad_silence_ms: int = 800
    vad_max_utterance_s: float = 15.0

    # Display
    display: str = "mock"
    display_fps: int = 12
    display_rotation: int = 0
    display_spi_hz: int = 32_000_000
    display_spi_mode: int = 3
    display_dc_pin: int = 25
    display_rst_pin: int = 27
    display_bl_pin: int = 24
    display_x_offset: int | None = None
    display_y_offset: int | None = None
    display_preview_path: str = ""
    eye_color: tuple[int, int, int] = (0x35, 0xD0, 0xFF)
    idle_sleep_s: float = 180.0

    # Memory
    memory_db_path: Path = PROJECT_ROOT / "data" / "meow.db"
    memory_persist_history: bool = True
    memory_max_turns: int = 40
    memory_max_facts: int = 200

    # Movement
    movement_enabled: bool = False
    motors: str = "mock"
    motor_ain1_pin: int = 5
    motor_ain2_pin: int = 6
    motor_pwma_pin: int = 12
    motor_bin1_pin: int = 16
    motor_bin2_pin: int = 26
    motor_pwmb_pin: int = 13
    motor_stby_pin: int = 23
    motor_max_speed: float = 0.6
    motor_default_speed: float = 0.5
    motor_max_run_s: float = 2.0
    motor_default_run_s: float = 1.0

    # Logging
    log_level: str = "INFO"
    log_file: Path = PROJECT_ROOT / "logs" / "meow.log"

    @classmethod
    def from_env(
        cls,
        env_file: Path | str | None = DEFAULT_ENV_FILE,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        """Load settings from ``env_file`` overlaid with ``environ`` (default: ``os.environ``).

        Raises:
            ConfigError: listing every invalid value.
        """
        values: dict[str, str | None] = {}
        if env_file and Path(env_file).is_file():
            values.update(dotenv_values(env_file))
        values.update(os.environ if environ is None else environ)
        r = _Reader(values)

        linux = _on_linux()
        tts_mode = r.choice("TTS_PROVIDER", "auto", ("auto", "svara", "mock"))
        stt_mode = r.choice("STT_PROVIDER", "auto", ("auto", "openai_compatible", "mock"))
        svara_key, svara_url = r.str("SVARA_API_KEY"), r.str("SVARA_BASE_URL").rstrip("/")
        stt_key = r.str("STT_API_KEY")

        movement_enabled = r.bool("MOVEMENT_ENABLED", False)
        motors_mode = r.choice("MOTORS", "auto", ("auto", "real", "mock"))
        # Motors only become real when movement is explicitly enabled.
        motors = "real" if motors_mode == "real" else (
            "mock" if motors_mode == "mock" else ("real" if movement_enabled and linux else "mock")
        )

        if tts_mode == "svara" and not (svara_key and svara_url):
            r.problems.append("TTS_PROVIDER=svara needs SVARA_API_KEY and SVARA_BASE_URL")
        if stt_mode == "openai_compatible" and not stt_key:
            r.problems.append("STT_PROVIDER=openai_compatible needs STT_API_KEY")

        rotation = r.int("DISPLAY_ROTATION", 0)
        if rotation not in (0, 90, 180, 270):
            r.problems.append(f"DISPLAY_ROTATION must be 0, 90, 180 or 270 (got {rotation})")
            rotation = 0

        def path(key: str, default: Path) -> Path:
            raw = r.str(key)
            p = Path(raw).expanduser() if raw else default
            return p if p.is_absolute() else PROJECT_ROOT / p

        level = r.str("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            r.problems.append(f"LOG_LEVEL is invalid (got {level!r})")
            level = "INFO"

        d = cls()
        settings = cls(
            llm_provider=r.choice("LLM_PROVIDER", d.llm_provider, ("openrouter",)),
            openrouter_api_key=r.str("OPENROUTER_API_KEY"),
            openrouter_model=r.str("OPENROUTER_MODEL", d.openrouter_model),
            openrouter_url=r.str("OPENROUTER_URL", d.openrouter_url),
            llm_timeout_s=r.float("LLM_TIMEOUT_S", d.llm_timeout_s, 1, 300),
            llm_max_retries=r.int("LLM_MAX_RETRIES", d.llm_max_retries, 0, 10),
            llm_max_tokens=r.int("LLM_MAX_TOKENS", d.llm_max_tokens, 16, 4096),
            llm_temperature=r.float("LLM_TEMPERATURE", d.llm_temperature, 0, 2),
            llm_json_mode=r.bool("LLM_JSON_MODE", d.llm_json_mode),
            history_token_budget=r.int("HISTORY_TOKEN_BUDGET", d.history_token_budget, 100, 32000),
            history_max_messages=r.int("HISTORY_MAX_MESSAGES", d.history_max_messages, 2, 200),
            tts_provider=("svara" if svara_key and svara_url else "mock") if tts_mode == "auto" else tts_mode,
            svara_api_key=svara_key,
            svara_base_url=svara_url,
            svara_voice=r.str("SVARA_VOICE", d.svara_voice),
            svara_timeout_s=r.float("SVARA_TIMEOUT_S", d.svara_timeout_s, 1, 300),
            svara_emotion_tags=r.bool("SVARA_EMOTION_TAGS", d.svara_emotion_tags),
            input_mode=r.choice("INPUT_MODE", d.input_mode, ("text", "voice")),
            listen_timeout_s=r.float("LISTEN_TIMEOUT_S", d.listen_timeout_s, 1, 600),
            barge_in=r.bool("BARGE_IN", d.barge_in),
            stt_provider="openai_compatible" if (stt_mode == "auto" and stt_key) else
            ("mock" if stt_mode == "auto" else stt_mode),
            stt_base_url=r.str("STT_BASE_URL", d.stt_base_url).rstrip("/"),
            stt_api_key=stt_key,
            stt_model=r.str("STT_MODEL", d.stt_model),
            stt_language=r.str("STT_LANGUAGE", d.stt_language),
            stt_timeout_s=r.float("STT_TIMEOUT_S", d.stt_timeout_s, 1, 300),
            audio_in=_auto(r.choice("AUDIO_IN", "auto", ("auto", "real", "mock")),
                           linux and shutil.which("arecord") is not None),
            audio_out=_auto(r.choice("AUDIO_OUT", "auto", ("auto", "real", "mock")),
                            linux and shutil.which("aplay") is not None),
            audio_in_device=r.str("AUDIO_IN_DEVICE", d.audio_in_device),
            audio_out_device=r.str("AUDIO_OUT_DEVICE", d.audio_out_device),
            mic_gain=r.float("MIC_GAIN", d.mic_gain, 0.1, 64),
            vad_min_rms=r.float("VAD_MIN_RMS", d.vad_min_rms, 1, 20000),
            vad_threshold_factor=r.float("VAD_THRESHOLD_FACTOR", d.vad_threshold_factor, 1, 20),
            vad_silence_ms=r.int("VAD_SILENCE_MS", d.vad_silence_ms, 200, 5000),
            vad_max_utterance_s=r.float("VAD_MAX_UTTERANCE_S", d.vad_max_utterance_s, 2, 60),
            display=_auto(r.choice("DISPLAY", "auto", ("auto", "real", "mock")),
                          linux and Path("/dev/spidev0.0").exists()),
            display_fps=r.int("DISPLAY_FPS", d.display_fps, 1, 30),
            display_rotation=rotation,
            display_spi_hz=r.int("DISPLAY_SPI_HZ", d.display_spi_hz, 1_000_000, 62_500_000),
            display_spi_mode=int(r.choice("DISPLAY_SPI_MODE", str(d.display_spi_mode), ("0", "3"))),
            display_dc_pin=r.pin("DISPLAY_DC_PIN", d.display_dc_pin),
            display_rst_pin=r.pin("DISPLAY_RST_PIN", d.display_rst_pin),
            display_bl_pin=r.pin("DISPLAY_BL_PIN", d.display_bl_pin),
            display_x_offset=r.optional_int("DISPLAY_X_OFFSET"),
            display_y_offset=r.optional_int("DISPLAY_Y_OFFSET"),
            display_preview_path=r.str("DISPLAY_PREVIEW_PATH"),
            eye_color=r.color("EYE_COLOR", d.eye_color),
            idle_sleep_s=r.float("IDLE_SLEEP_S", d.idle_sleep_s, 5, 86400),
            memory_db_path=path("MEMORY_DB_PATH", d.memory_db_path),
            memory_persist_history=r.bool("MEMORY_PERSIST_HISTORY", d.memory_persist_history),
            memory_max_turns=r.int("MEMORY_MAX_TURNS", d.memory_max_turns, 0, 1000),
            memory_max_facts=r.int("MEMORY_MAX_FACTS", d.memory_max_facts, 1, 5000),
            movement_enabled=movement_enabled,
            motors=motors,
            motor_ain1_pin=r.pin("MOTOR_AIN1_PIN", d.motor_ain1_pin),
            motor_ain2_pin=r.pin("MOTOR_AIN2_PIN", d.motor_ain2_pin),
            motor_pwma_pin=r.pin("MOTOR_PWMA_PIN", d.motor_pwma_pin),
            motor_bin1_pin=r.pin("MOTOR_BIN1_PIN", d.motor_bin1_pin),
            motor_bin2_pin=r.pin("MOTOR_BIN2_PIN", d.motor_bin2_pin),
            motor_pwmb_pin=r.pin("MOTOR_PWMB_PIN", d.motor_pwmb_pin),
            motor_stby_pin=r.pin("MOTOR_STBY_PIN", d.motor_stby_pin),
            motor_max_speed=r.float("MOTOR_MAX_SPEED", d.motor_max_speed, 0.1, 1.0),
            motor_default_speed=r.float("MOTOR_DEFAULT_SPEED", d.motor_default_speed, 0.1, 1.0),
            motor_max_run_s=r.float("MOTOR_MAX_RUN_S", d.motor_max_run_s, 0.1, 10.0),
            motor_default_run_s=r.float("MOTOR_DEFAULT_RUN_S", d.motor_default_run_s, 0.1, 10.0),
            log_level=level,
            log_file=path("LOG_FILE", d.log_file),
        )
        if r.problems:
            raise ConfigError(r.problems)
        return settings

    def secrets(self) -> list[str]:
        """Non-empty secret values, used by the log redaction filter."""
        return [s for s in (self.openrouter_api_key, self.svara_api_key, self.stt_api_key) if s]

    def check_ready_for_conversation(self) -> list[str]:
        """Problems that stop a real conversation (not needed for hardware tests)."""
        problems = []
        if not self.openrouter_api_key:
            problems.append("OPENROUTER_API_KEY is missing (set it in config/.env)")
        return problems

    def redacted(self) -> dict[str, object]:
        """Settings as a dict that is safe to log."""
        out: dict[str, object] = {}
        for name, value in self.__dict__.items():
            if "api_key" in name:
                out[name] = "set" if value else "missing"
            else:
                out[name] = str(value) if isinstance(value, Path) else value
        return out
