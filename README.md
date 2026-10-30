# 🐱 Meow Meow — AI companion robot

A small, affectionate companion robot for a Raspberry Pi Zero W: it listens, answers with an LLM
(OpenRouter), speaks with Svara TTS, shows emotions on animated eyes (ST7789), remembers things you
ask it to, and can drive on two wheels (TB6612FNG) — safely.

Everything hardware-related has a mock, so you can develop without any parts connected.

```
Mic → VAD → cloud STT → ConversationManager ──► OpenRouter
                              │  ▲ memory (SQLite)      │
                              ▼  └───────────────────── reply {message, emotion}
                       EventBus ──► DisplayManager ──► eyes
                              └───► SpeechOutput ──► Svara TTS ──► aplay ──► speaker
              movement phrases ──► MotionSafety ──► MotorController ──► TB6612FNG
```

## Quick start (no hardware needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp config/.env.example config/.env        # add OPENROUTER_API_KEY
python -m src.main                         # type to chat
python -m src.main --mock-all --mock-llm   # no keys, no hardware
pytest                                     # 137 tests
```
On the Pi follow **[docs/ASSEMBLY.md](docs/ASSEMBLY.md)** — it builds the robot step by step with a test per component.

## Layout

```
src/
  main.py                  CLI entry (python -m src.main [--voice] [--mock-all] [--mock-llm])
  config/settings.py       typed, validated, env-based configuration (config/.env)
  core/                    application loop, event bus, state manager, factory, logging
  ai/                      openrouter_client (retries/timeouts), conversation_manager, personality
  voice/                   audio_capture (VAD), speech_recognition (STT), svara_client (TTS),
                           audio_player, speech_output (sentence pipelining), listener
  display/                 expressions (data), animations (math), eye_renderer, display_manager
  hardware/                gpio_manager (pin registry), microphone, speaker, display_device (ST7789)
  movement/                safety, motor_controller (TB6612FNG), intents (voice commands)
  memory/                  database + memory_manager (SQLite)
tests/ …                   unit + end-to-end tests mirroring src/
scripts/                   hwtest.py (per-component tests), setup_pi.sh
deploy/meow-meow.service   systemd unit
```
Changes from the suggested structure: added `core/factory.py` (the one place that chooses real vs mock
components), `voice/audio_utils.py` and `voice/listener.py`, `display/eye_renderer.py` + `palette.py`
(so appearance can be replaced independently), `movement/intents.py`, and `ai/mock_llm.py`.
Audio uses `arecord`/`aplay` rather than PyAudio (no compiled dependency, little RAM), and
`requirements.txt` now lists only real dependencies — the old file was a full `pip freeze` of the Pi
(cloud-init, python-apt, `types-*`…) and did not even list `python-dotenv`.

## Design decisions

- **Lightweight.** One asyncio loop, no worker processes. Blocking HTTP runs via `asyncio.to_thread`;
  the display only renders/sends a frame when it would look different; speech is synthesised one
  sentence ahead of playback; audio is piped to `aplay` (no temp files).
- **Emotion protocol.** The model is asked for `{"message": "...", "emotion": "HAPPY"}`. Parsing
  tolerates code fences, chatter, truncated JSON and plain text; malformed output never crashes anything.
- **Memory.** Facts are saved only when you say "remember that …"; "forget …" / "forget everything"
  work too. A short rolling window of recent turns survives restarts (`MEMORY_PERSIST_HISTORY=false` turns it off).
  Credential-looking text is refused. The DB is `chmod 600`, git-ignored and never logged.
- **Movement safety.** Off by default → needs `MOVEMENT_ENABLED=true` → needs a runtime "enable movement"
  → speed/time capped → auto-stop → latched emergency stop. Driver starts and ends with STBY low.
  Only whole-utterance commands are recognised; normal chat can't move the robot.
- **Secrets.** Only in `config/.env` / environment. Not in `repr()`, logs (masked), or error messages.
- **Pins.** All GPIO assignments live in one registry; conflicts abort startup with a clear message.

## Assumptions to verify on your hardware

These could not be tested without the parts, so each has a test step and a documented fix:
1. **Svara auth/base URL.** Svara's public docs describe an OpenAI-compatible server
   (`POST /v1/audio/speech`, voices like `en_female`) but no hosted endpoint or auth header. The client
   sends `Authorization: Bearer <key>` when a key is set.
2. **I²S overlay.** `dtoverlay=googlevoicehat-soundcard` is the usual way to share one I²S bus between an INMP441 and a MAX98357A.
3. **ST7789 SPI mode and RAM offsets** vary by module (`DISPLAY_SPI_MODE`, `DISPLAY_*_OFFSET`).
4. **Wake word** is not implemented yet; barge-in (`BARGE_IN`) is experimental.

## Commands

| | |
|---|---|
| `python -m src.main --check-config` | validate configuration |
| `python -m src.main --pins` | print the wiring table |
| `python -m scripts.hwtest <pins\|audio-devices\|speaker\|mic\|tts\|stt\|display\|motors>` | component tests |
| `/help` `/status` `/forget` `/resetestop` `/quit` | inside the app |
