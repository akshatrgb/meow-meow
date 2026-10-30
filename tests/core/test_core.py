import asyncio
import logging

import pytest

from src.ai.mock_llm import MockChatClient
from src.ai.openrouter_client import LLMAuthError, LLMConnectionError
from src.config.settings import ConfigError, Settings
from src.core.application import Application
from src.core.event_bus import STATE_CHANGED, EventBus
from src.core.factory import Components
from src.core.logging_setup import SecretFilter
from src.core.state_manager import State
from src.hardware.gpio_manager import PinConflictError, PinRegistry, build_pin_registry
from src.memory.memory_manager import MemoryManager
from src.movement.motor_controller import MockMotorDriver, MotorController
from src.movement.safety import MotionSafety
from src.ai.conversation_manager import ConversationManager
from src.voice.audio_player import MockPlayer
from src.voice.listener import Listener
from src.voice.speech_output import SpeechOutput
from src.voice.svara_client import MockTTS


def load(env=None, **kw):
    return Settings.from_env(env_file=None, environ=env or {}, **kw)


# ------------------------------------------------------------------ settings
def test_defaults_are_safe_and_mocked():
    s = load()
    assert s.movement_enabled is False and s.motors == "mock"
    assert s.tts_provider == "mock" and s.stt_provider == "mock"
    assert s.openrouter_model == "openai/gpt-4.1-mini"


def test_secrets_are_hidden_from_repr_and_redacted_view():
    s = load({"OPENROUTER_API_KEY": "sk-or-topsecret", "SVARA_API_KEY": "svk-secret",
              "SVARA_BASE_URL": "https://x/v1"})
    assert "topsecret" not in repr(s) and "svk-secret" not in repr(s)
    assert "topsecret" not in str(s.redacted()) and s.redacted()["openrouter_api_key"] == "set"
    assert set(s.secrets()) == {"sk-or-topsecret", "svk-secret"}
    assert s.tts_provider == "svara"


def test_all_problems_reported_together():
    with pytest.raises(ConfigError) as info:
        load({"LLM_MAX_RETRIES": "many", "MOTOR_MAX_SPEED": "9", "DISPLAY_ROTATION": "45",
              "TTS_PROVIDER": "svara", "EYE_COLOR": "pink"})
    assert len(info.value.problems) == 5


def test_movement_enabled_unlocks_real_motors_only_on_request():
    assert load({"MOVEMENT_ENABLED": "true", "MOTORS": "mock"}).motors == "mock"


def test_env_file_is_read_and_environment_wins(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_MODEL=from/file  # comment\nEYE_COLOR=#ff0000\nOPENROUTER_API_KEY=\n")
    s = Settings.from_env(env_file=env, environ={})
    assert s.openrouter_model == "from/file" and s.eye_color == (255, 0, 0)
    s = Settings.from_env(env_file=env, environ={"OPENROUTER_MODEL": "from/env"})
    assert s.openrouter_model == "from/env"
    assert s.check_ready_for_conversation()  # empty key flagged


def test_shipped_env_example_parses():
    from src.config.settings import PROJECT_ROOT

    s = Settings.from_env(env_file=PROJECT_ROOT / "config" / ".env.example", environ={})
    assert s.eye_color == (0x35, 0xD0, 0xFF) and s.svara_voice == "en_female"


# ---------------------------------------------------------------------- pins
def test_default_pin_plan_has_no_conflicts():
    reg = build_pin_registry(load())
    gpios = [c.gpio for c in reg.table()]
    assert len(gpios) == len(set(gpios)) and {18, 19, 20, 21, 10, 11, 8}.issubset(gpios)


def test_pin_conflicts_are_detected():
    with pytest.raises(PinConflictError, match="GPIO25"):
        build_pin_registry(load({"MOTOR_AIN1_PIN": "25"}))
    with pytest.raises(PinConflictError, match="GPIO18"):
        build_pin_registry(load({"DISPLAY_BL_PIN": "18"}))
    with pytest.raises(PinConflictError):
        PinRegistry().claim("x", [1])


# ------------------------------------------------------------ bus and logging
def test_event_bus_isolates_failing_handlers():
    seen = []

    def bad(_):
        raise RuntimeError("boom")

    async def good(payload):
        seen.append(payload)

    async def scenario():
        bus = EventBus()
        bus.subscribe("t", bad)
        bus.subscribe("t", good)
        await bus.publish("t", 42)

    asyncio.run(scenario())
    assert seen == [42]


def test_secret_filter_redacts_log_messages():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "key=%s ok", ("sk-or-topsecret",), None)
    SecretFilter(["sk-or-topsecret"]).filter(record)
    assert "topsecret" not in record.getMessage() and "***" in record.getMessage()


# ------------------------------------------------------------------ end to end
class Scripted(Listener):
    def __init__(self, *inputs):
        self.inputs = list(inputs)

    async def listen(self, on_speech_start=None):
        if not self.inputs:
            raise EOFError
        item = self.inputs.pop(0)
        if item == "<speech>" and on_speech_start:
            await on_speech_start()
            return "hello"
        return item


def build_app(inputs, llm=None, movement=True):
    settings = load()
    memory = MemoryManager.open(None)
    player, driver = MockPlayer(0), MockMotorDriver()
    components = Components(
        conversation=ConversationManager(llm or MockChatClient(), memory),
        speech=SpeechOutput(MockTTS(), player), player=player, listener=Scripted(*inputs),
        motors=MotorController(driver, MotionSafety(movement)), memory=memory, display=None)
    app = Application(settings, components)
    states = []
    app.bus.subscribe(STATE_CHANGED, states.append)
    return app, player, driver, states


def test_text_conversation_speaks_and_returns_to_idle():
    app, player, _, states = build_app(["hi meow", "second one"])
    asyncio.run(app.run())
    assert len(player.played) >= 2
    assert states[:3] == [State.THINKING, State.SPEAKING, State.IDLE]


def test_quit_commands_end_the_loop_without_extra_input():
    app, player, _, _ = build_app(["/quit", "never reached"])
    asyncio.run(app.run())
    assert player.played == []


def test_listening_state_is_announced_when_speech_starts():
    app, _, _, states = build_app(["<speech>"])
    asyncio.run(app.run())
    assert states[0] is State.LISTENING


def test_offline_shows_offline_state_and_survives_then_recovers():
    class Flaky:
        n = 0

        async def acomplete(self, messages):
            Flaky.n += 1
            if Flaky.n == 1:
                raise LLMConnectionError("down", retryable=True)
            return '{"message": "I am back", "emotion": "HAPPY"}'

    app, player, _, states = build_app(["hi", "hi again"], llm=Flaky())
    asyncio.run(app.run())
    assert State.OFFLINE in states
    assert states[-1] is State.IDLE and len(player.played) == 1


def test_bad_api_key_reports_error_state():
    class Rejected:
        async def acomplete(self, messages):
            raise LLMAuthError("nope")

    app, _, _, states = build_app(["hi"], llm=Rejected())
    asyncio.run(app.run())
    assert State.ERROR in states


def test_motors_never_move_without_explicit_arming_and_end_safe():
    app, _, driver, _ = build_app(["forward", "enable movement", "forward", "emergency stop", "forward"])
    asyncio.run(app.run())
    moves = [c for c in driver.calls if c != (0.0, 0.0)]
    assert moves == [(0.5, 0.5)]          # only the one armed, un-latched command moved
    assert driver.calls[-1] == (0.0, 0.0) and driver.closed


def test_movement_disabled_in_config_never_moves():
    app, _, driver, _ = build_app(["enable movement", "forward"], movement=False)
    asyncio.run(app.run())
    assert all(c == (0.0, 0.0) for c in driver.calls)


def test_remember_command_flows_through_the_app():
    app, _, _, _ = build_app(["remember that my cat is called Miso"])
    asyncio.run(app.run())
    # memory is closed on shutdown; the turn must at least have completed without error
    assert app.state.state is State.IDLE
