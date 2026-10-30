"""The application loop: listen -> think -> express -> speak -> idle."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from src.ai.openrouter_client import LLMAuthError, LLMConnectionError, LLMError
from src.ai.personality import Emotion, Reply
from src.config.settings import Settings
from src.core.event_bus import (ASSISTANT_REPLIED, EMOTION_CHANGED, USER_SPOKE, EventBus)
from src.core.factory import Components
from src.core.state_manager import State, StateManager
from src.hardware.microphone import AudioError
from src.movement.intents import MoveIntent, parse_movement
from src.movement.safety import MovementDenied
from src.voice.svara_client import SVARA_EMOTION_TAGS, TTSError

log = logging.getLogger(__name__)

HELP = """Commands: /help  /quit  /status  /forget (wipe memory)  /resetestop
Say or type: "forward", "back", "turn left", "turn right", "stop", "emergency stop",
"enable movement", "disable movement", "remember that ...", "forget everything"."""


class Application:
    """Owns the main loop and the lifecycle of every component."""

    def __init__(self, settings: Settings, components: Components, bus: EventBus | None = None) -> None:
        self.settings = settings
        self.c = components
        self.bus = bus or EventBus()
        self.state = StateManager(self.bus)
        self._stopping = asyncio.Event()
        self._interactive = sys.stdout.isatty()
        if self.c.display is not None:
            self.c.display.attach(self.bus)

    def request_stop(self) -> None:
        self._stopping.set()

    # ------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        """Run until stopped by a signal, ``/quit`` or end of input."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:  # e.g. Windows
                pass
        if self.c.display is not None:
            self.c.display.start()
        log.info("Meow Meow is awake (input=%s)", self.settings.input_mode)
        self._print("\n🐱 Meow Meow is awake!  (type /help for commands)\n")
        try:
            while not self._stopping.is_set():
                text = await self._next_input()
                if text is None:
                    continue
                if text is _EXIT:
                    break
                await self._handle(text)
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        log.info("Shutting down")
        await self.c.player.stop()
        await self.c.motors.close()  # motors first: always reach a safe state
        if self.c.display is not None:
            await self.c.display.stop()
        self.c.memory.close()
        self._print("\nMeow Meow: Byeee! Meow meow! ❤️\n")

    async def _next_input(self):
        """Wait for user input, but wake immediately on a shutdown request."""

        async def on_speech_start() -> None:
            await self.state.set(State.LISTENING)

        listen = asyncio.create_task(self.c.listener.listen(on_speech_start))
        stop = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait({listen, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (listen, stop):
                task.cancel()
            await asyncio.gather(listen, stop, return_exceptions=True)
        if self._stopping.is_set():
            return _EXIT
        try:
            text = listen.result()
        except EOFError:
            return _EXIT
        except AudioError as error:
            log.error("Microphone problem: %s", error)
            await self.state.set(State.ERROR)
            await asyncio.sleep(2.0)  # avoid a hot loop if the mic is broken
            await self.state.set(State.IDLE)
            return None
        except Exception as error:  # noqa: BLE001 - e.g. STT outage; keep the robot alive
            log.error("Listening failed: %s", error)
            await self.state.set(State.IDLE)
            return None
        if text is None:
            await self.state.set(State.IDLE)
        return text

    # -------------------------------------------------------------- handling
    async def _handle(self, text: str) -> None:
        if self._interactive and self.settings.input_mode == "voice":
            self._print(f"You (heard): {text}")
        await self.bus.publish(USER_SPOKE, text)

        if text.lower() in {"exit", "quit", "/quit", "/exit"}:
            self.request_stop()
            return
        if text.startswith("/"):
            await self._command(text)
            return
        intent = parse_movement(text)
        if intent is not None:
            await self._movement(intent)
            return
        await self._converse(text)

    async def _command(self, text: str) -> None:
        name = text.lower().split()[0]
        if name == "/help":
            self._print(HELP)
        elif name == "/status":
            s = self.c.motors.safety
            self._print(f"state={self.state.state} tts={self.settings.tts_provider} "
                        f"stt={self.settings.stt_provider} movement_enabled={s.enabled} "
                        f"armed={s.armed} estop={s.estop_latched} history={self.c.conversation.history_length}")
        elif name == "/forget":
            self.c.conversation.clear()
            self._print("Memory wiped.")
        elif name == "/resetestop":
            self.c.motors.safety.reset_estop()
            self._print("Emergency stop reset. Movement is still disarmed.")
        else:
            self._print("Unknown command. Try /help")
        await self.state.set(State.IDLE)

    async def _movement(self, intent: MoveIntent) -> None:
        motors = self.c.motors
        try:
            if intent.action == "stop":
                await motors.stop()
                message = "Okay, stopped!"
            elif intent.action == "estop":
                await motors.emergency_stop()
                message = "Emergency stop! I won't move until you reset me."
            elif intent.action == "arm":
                motors.safety.arm()
                message = "Movement is on. Tell me where to go, but keep a hand near me."
            elif intent.action == "disarm":
                await motors.stop()
                motors.safety.disarm()
                message = "Movement is off. I'll stay put."
            else:
                direction = intent.direction
                assert direction is not None
                await motors.move(direction, duration_s=intent.duration_s)
                message = f"Going {direction.value}!"
        except MovementDenied as denied:
            message = f"I can't move: {denied}"
        await self._say(Reply(message, Emotion.NEUTRAL))

    async def _converse(self, text: str) -> None:
        await self.state.set(State.THINKING)
        try:
            reply = await self.c.conversation.respond(text)
        except LLMConnectionError as error:
            log.warning("Offline: %s", error)
            await self.state.set(State.OFFLINE)
            self._print("Meow Meow: I can't reach the internet right now. I'll keep trying when you talk to me.\n")
            return
        except LLMAuthError as error:
            log.error("LLM key rejected: %s", error)
            await self.state.set(State.ERROR)
            self._print("Meow Meow: My brain key was rejected. Please check OPENROUTER_API_KEY.\n")
            return
        except LLMError as error:
            log.error("LLM error: %s", error)
            await self._say(Reply("Hmm, my thoughts got tangled. Can you try again?", Emotion.CONFUSED))
            return
        await self.bus.publish(ASSISTANT_REPLIED, reply)
        await self._say(reply)

    async def _say(self, reply: Reply) -> None:
        """Show the emotion, print the words, speak them, then go idle."""
        await self.bus.publish(EMOTION_CHANGED, reply.emotion)
        await self.state.set(State.SPEAKING)
        self._print(f"\nMeow Meow: {reply.message}\n")
        tag = SVARA_EMOTION_TAGS.get(reply.emotion.value, "") if self.settings.svara_emotion_tags else ""
        try:
            await self._speak_interruptible(reply.message, tag)
        except (TTSError, AudioError) as error:
            log.warning("Could not speak: %s", error)
        await self.state.set(State.IDLE)

    async def _speak_interruptible(self, message: str, tag: str) -> None:
        speak = asyncio.create_task(self.c.speech.speak(message, tag))
        if not self.settings.barge_in:
            await speak
            return
        interrupt = asyncio.create_task(self.c.listener.wait_for_interruption())
        try:
            await asyncio.wait({speak, interrupt}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (speak, interrupt):
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(speak, interrupt, return_exceptions=True)
        if interrupt.done() and not interrupt.cancelled() and interrupt.exception() is None:
            log.info("Speech interrupted by the user")
        err = results[0]
        if isinstance(err, Exception) and not isinstance(err, asyncio.CancelledError):
            raise err

    def _print(self, message: str) -> None:
        """Terminal output only when a person is watching (never into the journal)."""
        if self._interactive:
            print(message, flush=True)


_EXIT = object()
