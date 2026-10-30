import asyncio
import math
import struct

from src.hardware.microphone import ListSource
from src.voice.audio_capture import AudioCapture, UtteranceDetector, VadEvent
from src.voice.audio_utils import apply_gain, pcm_to_wav, rms, wav_duration

RATE = 16000
CHUNK = int(RATE * 0.03)


def tone(amp: int, n: int = CHUNK) -> bytes:
    return b"".join(struct.pack("<h", int(amp * math.sin(i * 0.3))) for i in range(n))


QUIET, LOUD = tone(40), tone(6000)


def test_rms_and_gain():
    assert rms(b"") == 0.0
    assert 4000 < rms(LOUD) < 4400
    assert rms(apply_gain(QUIET, 10.0)) > 5 * rms(QUIET)
    assert apply_gain(LOUD, 100.0)  # clipping must not raise


def test_wav_round_trip_duration():
    wav = pcm_to_wav(b"\x00\x00" * RATE, RATE)
    assert abs(wav_duration(wav) - 1.0) < 0.01
    assert wav_duration(b"garbage") == 0.0


def run_detector(chunks, **kw):
    det = UtteranceDetector(RATE, **kw)
    events = [det.feed(c) for c in chunks]
    return det, events


def test_silence_and_noise_never_trigger():
    _, events = run_detector([QUIET] * 100)
    assert set(events) == {VadEvent.NONE}


def test_short_click_is_ignored():
    _, events = run_detector([QUIET] * 10 + [LOUD] + [QUIET] * 10)
    assert VadEvent.SPEECH_STARTED not in events


def test_speech_then_silence_completes_with_preroll():
    det, events = run_detector([QUIET] * 20 + [LOUD] * 15 + [QUIET] * 40)
    assert VadEvent.SPEECH_STARTED in events
    assert events.index(VadEvent.UTTERANCE_COMPLETE) > events.index(VadEvent.SPEECH_STARTED)
    audio = det.audio()
    assert len(audio) > 15 * len(LOUD)          # includes the speech...
    assert len(audio) < (15 + 40 + 12) * len(LOUD)  # ...but not all the leading silence


def test_max_length_cuts_off_endless_speech():
    _, events = run_detector([LOUD] * 200, max_utterance_s=2)
    assert VadEvent.UTTERANCE_COMPLETE in events


def test_threshold_scale_raises_the_bar():
    _, events = run_detector([tone(1200)] * 30, threshold_scale=1.0)
    assert VadEvent.SPEECH_STARTED in events
    _, events = run_detector([tone(1200)] * 30, threshold_scale=10.0)
    assert VadEvent.SPEECH_STARTED not in events


def test_capture_returns_utterance_and_fires_speech_hook():
    source = ListSource([QUIET] * 10 + [LOUD] * 15 + [QUIET] * 40)
    capture = AudioCapture(source)
    started = []
    pcm = asyncio.run(capture.record_utterance(5, lambda: started.append(1)))
    assert pcm and started == [1] and source.started and source.stopped


def test_capture_times_out_on_silence():
    source = ListSource([])
    assert asyncio.run(AudioCapture(source).record_utterance(0.2)) is None
    assert source.stopped


def test_wait_for_interruption_returns_on_loud_speech():
    source = ListSource([QUIET] * 5 + [tone(20000)] * 30)
    asyncio.run(asyncio.wait_for(AudioCapture(source).wait_for_interruption(), 3))
    assert source.stopped
