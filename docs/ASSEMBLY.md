# Meow Meow — assembly & bring-up guide

Build the robot **one component at a time**. Every step has a wiring table, one test
command, what a pass looks like, and what to check if it fails. **Do not move on until a
step passes** — when something breaks later you will know exactly which step caused it.

> **Always power the Pi off (`sudo poweroff`, then unplug) before changing wiring.**
> Wire to the Pi's 40-pin header; numbers below are the *physical* pin number (and the
> BCM GPIO in brackets). `python -m scripts.hwtest pins` prints the same table from the code,
> and the code refuses to start if two components claim the same pin.

| Step | Component | Test command | Needs hardware |
|---|---|---|---|
| 0 | Pi OS, project, keys | `python -m src.main --check-config` | no |
| 1 | Brain (typed chat) | `python -m src.main` | no |
| 2 | Speaker + amp (MAX98357A) | `python -m scripts.hwtest speaker` | yes |
| 3 | Microphone (INMP441) | `python -m scripts.hwtest mic` | yes |
| 4 | Svara voice | `python -m scripts.hwtest tts` | speaker |
| 5 | Voice conversation | `python -m src.main --voice` | mic + speaker |
| 6 | Display eyes (ST7789) | `python -m scripts.hwtest display` | yes |
| 7 | Motors (TB6612FNG) | `python -m scripts.hwtest motors …` | yes |
| 8 | Autostart | `systemctl status meow-meow` | all |

Before you start you can try everything with no hardware: `python -m src.main --mock-all --mock-llm`.

---

## Step 0 — Pi, project and keys

1. Flash **Raspberry Pi OS Lite 32-bit**, enable Wi-Fi + SSH (Raspberry Pi Imager, advanced options), boot, `ssh` in.
2. Get the project and install:
   ```bash
   cd ~ && git clone https://github.com/akshatrgb/meow-meow.git && cd meow-meow
   git pull          # make sure you have this version
   bash scripts/setup_pi.sh
   ```
3. Put your keys in `config/.env` (the file is git-ignored; never paste keys in chat/commits):
   ```bash
   nano config/.env      # OPENROUTER_API_KEY=...  (Svara/STT keys come later)
   ```
4. **Test:** `.venv/bin/python -m src.main --check-config` → `Configuration OK`.
   If it lists problems, fix those lines — it reports all of them at once.

Python note: the code needs Python ≥ 3.11 (you have 3.13). If `pip install` of Pillow fails on
the Zero's ARMv6 CPU, `setup_pi.sh` already installs `python3-pil` and the venv uses it
(`--system-site-packages`).

## Step 1 — The brain, no hardware

```bash
source .venv/bin/activate
python -m src.main
```
Chat by typing. Try: `remember that my favourite colour is blue`, then restart and ask
`what colour do I like?`. Say `/help` for commands, `/quit` to leave.

**Pass:** friendly short replies; no errors. Unplug Wi-Fi mid-chat: it should say it
can't reach the internet instead of crashing, and recover when Wi-Fi returns.

## Step 2 — Speaker: MAX98357A amplifier

Wiring (Pi powered **off**):

| MAX98357A | → Pi physical pin (GPIO) |
|---|---|
| VIN | 2 (5V) |
| GND | 6 (GND) |
| BCLK | 12 (GPIO18) |
| LRC | 35 (GPIO19) |
| DIN | 40 (GPIO21) |
| SD, GAIN | leave unconnected (mono mix, 9 dB gain) |

Speaker (4–8 Ω) to the amp's screw terminals / `+` `–` pads.

Enable the I²S sound card. This one overlay serves **both** the amp and (in Step 3) the
microphone, because they share the same I²S clock pins:
```bash
sudo nano /boot/firmware/config.txt      # add at the end:
dtoverlay=googlevoicehat-soundcard
sudo reboot
```
**Test:**
```bash
aplay -l                                  # a card named like "sndrpigooglevoi" must appear
cd ~/meow-meow && source .venv/bin/activate
python -m scripts.hwtest speaker          # 2-second beep
```
**Pass:** a clean steady beep.
**If not:**
- No card in `aplay -l` → overlay line typo / didn't reboot / BCLK-LRC wires swapped.
- Card exists but silence → check `VIN` is 5 V, `DIN` goes to GPIO21; try
  `AUDIO_OUT_DEVICE=plughw:CARD=<card name from aplay -l>` in `config/.env`.
- Crackling/reboots when loud → power supply too weak (Zero needs a good 5 V 2 A supply).

## Step 3 — Microphone: INMP441

Wiring (Pi **off**). The INMP441 is **3.3 V only — never 5 V**.

| INMP441 | → Pi physical pin (GPIO) |
|---|---|
| VDD | 1 (3V3) |
| GND | 9 (GND) |
| SCK | 12 (GPIO18) — shared with amp BCLK |
| WS | 35 (GPIO19) — shared with amp LRC |
| SD | 38 (GPIO20) |
| L/R | GND (selects the left channel) |

**Test:**
```bash
arecord -l                                # the same card must be listed for capture
python -m scripts.hwtest mic --seconds 6  # stay quiet 2 s, then talk
```
The live bar should jump when you speak. The script prints suggested settings:
- Peak very low → raise `MIC_GAIN` in `config/.env` (INMP441 is quiet; try 4–8).
- It prints a suggested `VAD_MIN_RMS`; put it in `config/.env`.
- It saves `logs/mic_test.wav`; play it back with `aplay logs/mic_test.wav` — you should hear your voice.

**If not:** all zeros → check SD→GPIO20 and L/R→GND; flat noise → SCK/WS swapped or loose wire.
Set `AUDIO_IN_DEVICE` as in Step 2 if `default` is wrong.

## Step 4 — Svara voice

1. In `config/.env` set `SVARA_API_KEY`, `SVARA_BASE_URL` and `SVARA_VOICE`.
   Svara's documented API is OpenAI-compatible: the request goes to `<SVARA_BASE_URL>/audio/speech`,
   so the base URL must end in `/v1` (e.g. `https://your-host/v1`). Use the base URL from your
   Svara provider/dashboard. Voice ids look like `en_female`, `en_male`, `hi_female`.
2. **Test:**
   ```bash
   python -m scripts.hwtest tts --list-voices     # shows the voices your server offers
   python -m scripts.hwtest tts "Hello, I am Meow Meow!"
   ```
**Pass:** you hear Svara's voice. The command prints how long synthesis took.
**If not:** `401` → key/auth; `404` → base URL (missing `/v1`?); "not WAV" → the server ignored
`response_format`. Please send me the exact message (never the key) and I'll adapt the client:
Svara's public docs don't specify the auth header, so this is the one thing I could not verify.

## Step 5 — Voice conversation

1. Speech-to-text runs in the cloud (the Zero cannot run Whisper). Any OpenAI-compatible
   transcription service works; Groq's free tier is the default: create a key at console.groq.com and set
   `STT_API_KEY` in `config/.env`.
2. **Test:** `python -m scripts.hwtest stt` → say a sentence → it prints what it heard.
3. **Run:** `python -m src.main --voice`. Talk; Meow Meow replies out loud.

Tuning: if it cuts you off, raise `VAD_SILENCE_MS`; if it reacts to noise, raise `VAD_MIN_RMS`
or `VAD_THRESHOLD_FACTOR`. `BARGE_IN=true` lets you interrupt it mid-sentence, but with the
mic next to the speaker it can hear itself — enable it last and tune `VAD_*`.
Wake word is **not implemented yet** (planned later phase); for now it listens whenever idle.

## Step 6 — Display eyes: ST7789 1.3" (240×240)

**Question for you:** does your module have a **CS** pin? (Most 1.3" boards have 7 pins:
GND VCC SCL SDA RES DC BLK, with no CS.) Either is fine; it only changes one line.

Wiring (Pi **off**):

| Display | → Pi physical pin (GPIO) |
|---|---|
| VCC | 17 (3V3) |
| GND | 25 (GND) |
| SCL / SCK | 23 (GPIO11) |
| SDA / MOSI | 19 (GPIO10) |
| RES | 13 (GPIO27) |
| DC | 22 (GPIO25) |
| CS (if present) | 24 (GPIO8) |
| BLK / BL | 18 (GPIO24) |

Enable SPI: `sudo raspi-config` → Interface Options → SPI → Yes (or `dtparam=spi=on` in
`/boot/firmware/config.txt`), reboot, check `ls /dev/spidev0.0`.

**Test:** `python -m scripts.hwtest display` cycles all 10 expressions.
**Pass:** cute cyan eyes that change shape, blink, look around.
**If not:**
- Blank, backlight on → try `DISPLAY_SPI_MODE=0`; check RES/DC wires.
- Garbled / snow → lower `DISPLAY_SPI_HZ` to `16000000` (long jumper wires), try the other SPI mode.
- Picture shifted or a coloured band → set `DISPLAY_X_OFFSET` / `DISPLAY_Y_OFFSET` (0 or 80).
- Upside down/rotated → `DISPLAY_ROTATION=0|90|180|270`.
- Wrong colours (inverted) or too bright → `EYE_COLOR=#rrggbb`.

No Pi handy? `DISPLAY_PREVIEW_PATH=logs/eyes.png python -m scripts.hwtest display` writes a PNG preview.

## Step 7 — Motors: TB6612FNG (do this last)

Power rules (most robot problems come from here):
- Motors get their **own battery** on `VM` (4.5–13.5 V; use the voltage your motors are rated for).
  **Never power motors from the Pi's 5 V pin.** Put a 100 µF capacitor across VM–GND.
- Battery ground, TB6612 ground and Pi ground **must be connected together**.
- Add a **10 kΩ resistor STBY → GND** so motors stay off while the Pi boots (GPIO23 is also low by default).

| TB6612FNG | → connect to |
|---|---|
| VCC | Pi pin 1 (3V3) |
| GND | Pi pin 14 (GND) + battery − |
| VM | battery + (via a switch) |
| STBY | pin 16 (GPIO23) + 10 kΩ to GND |
| PWMA | pin 32 (GPIO12) |
| AIN1 / AIN2 | pin 29 (GPIO5) / pin 31 (GPIO6) |
| PWMB | pin 33 (GPIO13) |
| BIN1 / BIN2 | pin 36 (GPIO16) / pin 37 (GPIO26) |
| A01 / A02 | left motor |
| B01 / B02 | right motor |

**Test with the wheels OFF the ground** and a hand on the battery switch:
```bash
python -m scripts.hwtest motors --i-confirm-wheels-lifted            # mock: prints only
# then enable the real thing:
python -m scripts.hwtest motors --i-confirm-wheels-lifted --real
```
Sequence: forward, backward, left, right, 0.6 s each. If a wheel spins the wrong way, swap that
motor's two wires (A01↔A02 or B01↔B02) — no code change needed.

How movement stays safe in the app: it is off by default. To use it set `MOVEMENT_ENABLED=true`,
start the app, then say or type **"enable movement"**. After that "forward", "turn left",
"go back for 2 seconds", "stop" work; each move is capped (`MOTOR_MAX_RUN_S`, `MOTOR_MAX_SPEED`)
and stops itself. "Emergency stop" latches until you type `/resetestop`. Casual chat
("I can't stop thinking…") never moves it.

## Step 8 — Autostart on boot

```bash
nano deploy/meow-meow.service        # change User=/paths if your username is not "pi"
sudo cp deploy/meow-meow.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meow-meow
journalctl -u meow-meow -f           # watch it
```
Stop with `sudo systemctl stop meow-meow` (graceful: motors safe, screen blanked).
Under systemd, conversation text is **not** written to the journal (privacy).

---

## Troubleshooting quick list
- `python -m src.main --check-config` — configuration problems, all at once.
- `python -m scripts.hwtest audio-devices` — what ALSA sees.
- `logs/meow.log` — rotating log; API keys are masked automatically.
- Everything misbehaving at once on battery → power supply; measure 5 V under load.
