import os
import requests

from dotenv import load_dotenv
from .personality import SYSTEM_PROMPT

load_dotenv("config/.env")

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def chat(message, history=None):

    if not API_KEY:
        raise RuntimeError("OpenRouter API key is missing.")

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    if history:
        messages.extend(history)

    messages.append({
        "role": "user",
        "content": message
    })

    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 200
        },
        timeout=60
    )

    response.raise_for_status()

    result = response.json()

    return result["choices"][0]["message"]["content"]
