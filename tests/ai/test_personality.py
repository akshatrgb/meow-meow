import pytest

from src.ai.personality import (FALLBACK_MESSAGE, Emotion, Reply, build_system_prompt, parse_reply)


def test_parses_clean_json():
    r = parse_reply('{"message": "Heyyy! Meow meow!", "emotion": "HAPPY"}')
    assert r == Reply("Heyyy! Meow meow!", Emotion.HAPPY)


def test_parses_json_in_code_fence_and_lowercase_emotion():
    r = parse_reply('```json\n{"message": "Hi", "emotion": "love"}\n```')
    assert (r.message, r.emotion) == ("Hi", Emotion.LOVE)


def test_parses_json_surrounded_by_chatter():
    r = parse_reply('Sure! {"message": "Hello", "emotion": "CURIOUS"} hope that helps')
    assert (r.message, r.emotion) == ("Hello", Emotion.CURIOUS)


def test_unknown_emotion_falls_back_to_heuristic():
    r = parse_reply('{"message": "Oh no, I am sorry about that.", "emotion": "ECSTATIC"}')
    assert r.emotion is Emotion.SAD


def test_plain_text_is_used_as_the_message():
    r = parse_reply("Just some plain words.")
    assert r.message == "Just some plain words."
    assert r.emotion is Emotion.NEUTRAL


def test_truncated_json_recovers_the_message():
    r = parse_reply('{"message": "I was saying that you are', )
    assert r.message == "I was saying that you are"


@pytest.mark.parametrize("raw", [None, "", "   ", "{not json at all", '{"emotion": "HAPPY"}', "[]"])
def test_garbage_never_raises(raw):
    r = parse_reply(raw)
    assert isinstance(r, Reply) and r.message


def test_broken_json_is_never_read_aloud():
    assert parse_reply("{broken").message == FALLBACK_MESSAGE


def test_long_messages_are_capped():
    assert len(parse_reply('{"message": "' + "a" * 5000 + '"}').message) <= 600


def test_system_prompt_keeps_original_personality_and_adds_memory():
    prompt = build_system_prompt(["my name is Sam"], ["note"])
    assert "You are Meow Meow, a tiny AI robot companion." in prompt
    assert "my name is Sam" in prompt and "note" in prompt
    assert "never claim to have human feelings" in prompt.lower()
