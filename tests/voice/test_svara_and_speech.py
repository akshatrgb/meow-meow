import asyncio

import pytest
import requests

from src.voice.audio_player import MockPlayer
from src.voice.audio_utils import make_tone_wav
from src.voice.speech_output import SpeechOutput, split_sentences
from src.voice.speech_recognition import OpenAICompatibleRecognizer, STTError
from src.voice.svara_client import AudioClip, MockTTS, SvaraClient, TTSError, TTSProvider
from tests.conftest import FakeResponse, FakeSession

WAV = make_tone_wav(0.1)
KEY = "svara-secret-key-123"


def svara(session, key=KEY):
    return SvaraClient("https://tts.example/v1/", key, "en_female", session=session, sleep=lambda s: None)


def test_request_matches_documented_openai_compatible_contract():
    session = FakeSession(FakeResponse(200, content=WAV))
    clip = svara(session).synthesize_sync("Hello there")
    req = session.requests[0]
    assert req["url"] == "https://tts.example/v1/audio/speech"
    assert req["json"] == {"input": "Hello there", "voice": "en_female",
                           "response_format": "wav", "stream": False}
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert clip.data == WAV and clip.format == "wav"


def test_no_auth_header_without_key():
    session = FakeSession(FakeResponse(200, content=WAV))
    svara(session, key="").synthesize_sync("hi")
    assert "Authorization" not in session.requests[0]["headers"]


def test_transient_failure_is_retried_once():
    session = FakeSession(FakeResponse(503), FakeResponse(200, content=WAV))
    assert svara(session).synthesize_sync("hi").data == WAV
    assert len(session.requests) == 2


def test_network_error_becomes_tts_error_without_secret():
    session = FakeSession(*[requests.ConnectionError(f"boom {KEY}")] * 2)
    with pytest.raises(TTSError) as info:
        svara(session).synthesize_sync("hi")
    assert KEY not in str(info.value)


@pytest.mark.parametrize("status,match", [(401, "rejected"), (404, "SVARA_BASE_URL")])
def test_permanent_errors_are_not_retried(status, match):
    session = FakeSession(FakeResponse(status))
    with pytest.raises(TTSError, match=match):
        svara(session).synthesize_sync("hi")
    assert len(session.requests) == 1


def test_non_wav_body_is_rejected():
    session = FakeSession(FakeResponse(200, content=b"<html>nope</html>"))
    with pytest.raises(TTSError, match="not WAV"):
        svara(session).synthesize_sync("hi")


def test_list_voices_uses_voices_endpoint():
    session = FakeSession(FakeResponse(200, {"voices": ["en_female"]}))
    assert svara(session).list_voices() == {"voices": ["en_female"]}
    assert session.requests[0]["url"] == "https://tts.example/v1/voices"


def test_mock_tts_makes_playable_wav():
    clip = asyncio.run(MockTTS().synthesize("hello"))
    assert clip.data.startswith(b"RIFF")


def test_split_sentences_merges_tiny_fragments():
    assert split_sentences("Hi! How are you doing today? I am great.") == [
        "Hi! How are you doing today?", "I am great."]
    assert split_sentences("   ") == []


class RecordingTTS(TTSProvider):
    def __init__(self, fail_on=None):
        self.texts, self.fail_on = [], fail_on

    async def synthesize(self, text):
        if self.fail_on is not None and len(self.texts) == self.fail_on:
            raise TTSError("service down")
        self.texts.append(text)
        return AudioClip(WAV)


def test_speech_output_plays_every_sentence_in_order_with_tag():
    tts, player = RecordingTTS(), MockPlayer(0)
    asyncio.run(SpeechOutput(tts, player).speak("This is the first sentence we say. This is the second sentence we say.", "<happy>"))
    assert tts.texts == ["This is the first sentence we say. <happy>", "This is the second sentence we say. <happy>"]
    assert len(player.played) == 2


def test_speech_output_plays_what_it_has_then_raises_on_tts_failure():
    tts, player = RecordingTTS(fail_on=1), MockPlayer(0)
    with pytest.raises(TTSError):
        asyncio.run(SpeechOutput(tts, player).speak("This is the first sentence we say. This is the second sentence we say."))
    assert len(player.played) == 1


def test_cancelling_speech_stops_the_player():
    class SlowPlayer(MockPlayer):
        stopped = False

        async def play(self, clip):
            await asyncio.sleep(10)

        async def stop(self):
            self.stopped = True

    async def scenario():
        player = SlowPlayer()
        task = asyncio.create_task(SpeechOutput(RecordingTTS(), player).speak("Hello there friend."))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return player.stopped

    assert asyncio.run(scenario()) is True


def test_stt_request_shape_and_result():
    session = FakeSession(FakeResponse(200, {"text": "  hello world "}))
    rec = OpenAICompatibleRecognizer("https://stt.example/v1", "k", "whisper", "en", session=session)
    assert asyncio.run(rec.transcribe(WAV)) == "hello world"
    req = session.requests[0]
    assert req["url"] == "https://stt.example/v1/audio/transcriptions"
    assert req["data"]["model"] == "whisper" and req["files"]["file"][1] == WAV


@pytest.mark.parametrize("response", [FakeResponse(401), FakeResponse(500), FakeResponse(200)])
def test_stt_errors(response):
    rec = OpenAICompatibleRecognizer("https://stt.example/v1", "k", "m", session=FakeSession(response))
    with pytest.raises(STTError):
        asyncio.run(rec.transcribe(WAV))
