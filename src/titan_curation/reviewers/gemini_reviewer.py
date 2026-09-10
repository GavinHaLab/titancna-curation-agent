"""Gemini reviewer backend (Google GenAI API -- the current `google-genai` SDK;
the older `google-generativeai` package is deprecated and is not used here)."""
from __future__ import annotations

import json
import re

from .base import build_system_prompt, build_user_text


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def review(
    evidence: dict,
    top_candidates: list[dict],
    labeled_images: list[tuple[str, str]],
    knowledge_dir: str,
    api_key: str,
    model: str,
) -> dict:
    """labeled_images: list of (label, image_path)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    system_prompt = build_system_prompt(knowledge_dir)
    user_text = build_user_text(evidence, top_candidates, reviewer_name="gemini")

    contents = []
    for label, path in labeled_images:
        contents.append(f"[Image: {label}]")
        with open(path, "rb") as f:
            data = f.read()
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        contents.append(types.Part.from_bytes(data=data, mime_type=mime))
    contents.append(user_text)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return _extract_json(response.text)
