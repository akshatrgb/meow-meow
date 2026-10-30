"""Builds the concrete components for the configured mode (real or mock)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.ai.conversation_manager import ConversationManager
from src.ai.mock_llm import MockChatClient
from src.ai.openrouter_client import ChatClient, OpenRouterClient
from src.config.settings import Settings
from src.display.display_manager import DisplayManager
from src.hardware.display_device import create_display_device
from src.hardware.microphone import ArecordSource
from src.memory.memory_manager import MemoryManager
from src.movement.motor_controller import MotorController
from src.voice.audio_capture import AudioCapture
from src.voice.audio_player import AplayPlayer, AudioPlayer, MockPlayer
from src.voice.listener import Listener, TextListener, VoiceListener
from src.voice.speech_output import SpeechOutput
from src.voice.speech_recognition import MockRecognizer, OpenAICompatibleRecognizer, SpeechRecognizer
from src.voice.svara_client import MockTTS, SvaraClient, TTSProvider

log = logging.getLogger(__name__)


@dataclass
class Components:
    conversation: ConversationManager
    speech: SpeechOutput
    player: AudioPlayer
    listener: Listener
    motors: MotorController
    memory: MemoryManager
    display: DisplayManager | None


def build_display(s: Settings) -> DisplayManager | None:
    """The eyes. Skipped on a plain mock run (nothing would see them)."""
    if s.display == "mock" and not s.display_preview_path:
        return None
    try:
        from src.display.eye_renderer import EyeRenderer

        renderer = EyeRenderer()
    except ImportError:
        log.warning("Pillow is not installed; running without eyes (pip install Pillow)")
        return None
    return DisplayManager(create_display_device(s), renderer, fps=s.display_fps, idle_sleep_s=s.idle_sleep_s)


def build_listener(s: Settings) -> Listener:
    if s.input_mode == "voice":
        if s.audio_in != "real":
            log.warning("INPUT_MODE=voice but no microphone is available (AUDIO_IN=%s); using typed input",
                        s.audio_in)
        else:
            recognizer: SpeechRecognizer
            if s.stt_provider == "openai_compatible":
                recognizer = OpenAICompatibleRecognizer.from_settings(s)
            else:
                log.warning("No STT_API_KEY set: speech recognition is mocked")
                recognizer = MockRecognizer()
            capture = AudioCapture(
                ArecordSource(s.audio_in_device, s.sample_rate), gain=s.mic_gain, min_rms=s.vad_min_rms,
                threshold_factor=s.vad_threshold_factor, silence_ms=s.vad_silence_ms,
                max_utterance_s=s.vad_max_utterance_s)
            return VoiceListener(capture, recognizer, s.listen_timeout_s)
    return TextListener()


def build_components(s: Settings, *, mock_llm: bool = False) -> Components:
    """Assemble everything. Hardware that cannot be opened degrades to a mock."""
    llm: ChatClient = MockChatClient() if mock_llm else OpenRouterClient.from_settings(s)
    memory = MemoryManager.open(
        s.memory_db_path, max_turns=s.memory_max_turns, max_facts=s.memory_max_facts,
        persist_history=s.memory_persist_history and not mock_llm)
    conversation = ConversationManager(llm, memory, token_budget=s.history_token_budget,
                                       max_messages=s.history_max_messages)

    tts: TTSProvider = SvaraClient.from_settings(s) if s.tts_provider == "svara" else MockTTS()
    player: AudioPlayer = AplayPlayer(s.audio_out_device) if s.audio_out == "real" else MockPlayer()
    return Components(
        conversation=conversation,
        speech=SpeechOutput(tts, player),
        player=player,
        listener=build_listener(s),
        motors=MotorController.from_settings(s),
        memory=memory,
        display=build_display(s),
    )
