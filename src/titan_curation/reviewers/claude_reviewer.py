"""Claude Sonnet reviewer backend (Anthropic API)."""
from __future__ import annotations

import base64
import json
import re

from .base import build_system_prompt, build_user_text

MAX_TOKENS = 4096


def _image_block(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    media_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip accidental markdown fencing if the model adds it anyway.
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
    """labeled_images: list of (label, image_path), e.g.
    ("ploidy2_cluster1 - genome-wide CNA", "/path/to/img.png")."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = build_system_prompt(knowledge_dir)
    user_text = build_user_text(evidence, top_candidates, reviewer_name="claude_sonnet")

    content = []
    for label, path in labeled_images:
        content.append({"type": "text", "text": f"[Image: {label}]"})
        content.append(_image_block(path))
    content.append({"type": "text", "text": user_text})

    message = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    raw_text = "".join(block.text for block in message.content if block.type == "text")
    return _extract_json(raw_text)
