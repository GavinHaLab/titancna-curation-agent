"""Reviewer backend that routes BOTH the "claude" and "gemini" reviewer roles
through a single Perplexity API key, via Perplexity's Agent API
(`POST /v1/agent`, official `perplexityai` Python SDK). This lets a user with
only a `PERPLEXITY_API_KEY` (no separate Anthropic/Google keys) run the same
two-reviewer methodology, by pointing the same call at two different
`provider/model` IDs:

  - Claude role: model="anthropic/claude-sonnet-5" (or any anthropic/* id)
  - Gemini role: model="google/gemini-3.1-pro-preview" (or any google/* id)

Reference: https://docs.perplexity.ai/docs/agent-api/image-attachments and
https://docs.perplexity.ai/docs/agent-api/quickstart (fetched 2026-09-21).

Images are embedded as base64 data URIs directly in the request (no public
hosting required -- this works from an air-gapped HPC node with outbound
HTTPS only). `max_output_tokens` is REQUIRED by the API for anthropic/*
models (HTTP 400 otherwise) so it is always sent regardless of provider.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re

from .base import build_system_prompt, build_user_text

MAX_OUTPUT_TOKENS = 4096


def _image_content_part(path: str) -> dict:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}


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
    reviewer_name: str,
) -> dict:
    """labeled_images: list of (label, image_path). `reviewer_name` must be
    exactly "claude_sonnet" or "gemini" -- it is threaded into the shared
    prompt so the model's JSON `reviewer` field and this backend's role stay
    consistent regardless of which underlying `model` id is actually called."""
    from perplexity import Perplexity

    client = Perplexity(api_key=api_key)
    system_prompt = build_system_prompt(knowledge_dir)
    user_text = build_user_text(evidence, top_candidates, reviewer_name=reviewer_name)

    content = []
    for label, path in labeled_images:
        content.append({"type": "input_text", "text": f"[Image: {label}]"})
        content.append(_image_content_part(path))
    content.append({"type": "input_text", "text": user_text})

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=[{"type": "message", "role": "user", "content": content}],
        max_output_tokens=MAX_OUTPUT_TOKENS,
        stream=False,
    )
    return _extract_json(response.output_text)
