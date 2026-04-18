# core/gemini_client.py
# Shared Gemini client factory — uses the NEW google.genai package.
# All project files should use this instead of the deprecated google.generativeai.

import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def ask(prompt: str, model: str = "gemini-2.5-flash-lite",
        system_instruction: str = None) -> str:
    """Simple one-shot text generation. Returns response text."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_api_key())

    config = None
    if system_instruction:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction
        )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )
    return response.text.strip()


def ask_with_image(prompt: str, image_data: bytes,
                   mime_type: str = "image/png",
                   model: str = "gemini-2.5-flash-lite") -> str:
    """One-shot generation with an image input."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_api_key())

    contents = [
        types.Part.from_bytes(data=image_data, mime_type=mime_type),
        prompt,
    ]

    response = client.models.generate_content(
        model=model,
        contents=contents,
    )
    return response.text.strip()
