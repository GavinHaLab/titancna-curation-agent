"""Reviewer backend that routes BOTH independent reviewer roles through a
single Perplexity API key, via Perplexity's Agent API (`POST /v1/agent`,
official `perplexityai` Python SDK). A single `PERPLEXITY_API_KEY` runs the
two-reviewer methodology by pointing the same call at two different
`provider/model` IDs:

  - Claude role: model="anthropic/claude-sonnet-5-5" (or any anthropic/* id)
  - Second role: model="openai/gpt-5.5" (or any provider/* id)

Reference: https://docs.perplexity.ai/docs/agent-api/image-attachments and
https://docs.perplexity.ai/docs/agent-api/quickstart (fetched 2026-09-21).

Images are embedded as base64 data URIs directly in the request (no public
hosting required -- this works from an air-gapped HPC node with outbound
HTTPS only). `max_output_tokens` is REQUIRED by the API for anthropic/*
models (HTTP 400 otherwise) so it is always sent regardless of provider.

Perplexity enforces a hard request-body size limit that rejects the whole
request with a generic HTTP 400 "invalid request" (no size-specific message)
-- confirmed empirically: a real ~7MB base64 payload (29 full-resolution
plot PNGs) was rejected instantly, while a ~4.8MB payload (20 images) was
accepted and proceeded to real model generation. Plots are line/scatter
charts, not photos, so they compress and downscale with no meaningful loss
of the axis/band detail the reviewer needs -- every embedded image is
therefore downscaled and re-encoded as JPEG before being sent, which keeps
even the full 29-image, top-5-candidate payload well under that limit.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import time

from .base import build_system_prompt, build_user_text

# Retry budget for HTTP 429 (rate limit exceeded). Batch mode makes several
# of these calls back to back across samples/reviewer roles; a burst/window
# limit on the account can trip even at a low nominal QPS. Retries with
# exponential backoff, honoring the API's Retry-After header when present,
# rather than failing the whole sample on a transient rate limit.
MAX_RATE_LIMIT_RETRIES = 6
RATE_LIMIT_BACKOFF_BASE_SECONDS = 10

# anthropic/* models on this endpoint spend a large chunk of max_output_tokens
# on internal reasoning before emitting the final JSON -- observed 6213
# reasoning tokens alone out of an 8192 cap, truncating the JSON mid-array.
# 24576 leaves ample room for reasoning plus the full ranked_candidates/flags/
# 750-word comment JSON body.
MAX_OUTPUT_TOKENS = 24576

# Plots are wide, mostly-white matplotlib/R charts -- these settings keep
# every axis label and band legible while giving real headroom under the
# empirically-confirmed ~5-6MB request-body ceiling even for cohort samples
# with many ploidy-doubling-ambiguity flags (up to ~46 images/sample seen in
# practice). Benchmarked on real plots (29-image sample, scaled to 46):
#   max_dim=1400 q=85 -> ~5.47MB  (too close to the real ceiling)
#   max_dim=1100 q=80 -> ~3.31MB  (chosen: comfortable margin, quality fine)
#   max_dim=1000 q=75 -> ~2.52MB
IMAGE_MAX_DIM = 1100
IMAGE_JPEG_QUALITY = 80


def _image_content_part(path: str) -> dict:
    from PIL import Image

    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > IMAGE_MAX_DIM:
        img.thumbnail((IMAGE_MAX_DIM, IMAGE_MAX_DIM), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}"}


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _get(obj, key):
    """response.output items come back as plain dicts in this SDK version
    (not attribute-objects) when their shape doesn't match one of the
    Pydantic-typed output-item variants -- e.g. a normal "message" item still
    triggers PydanticSerializationUnexpectedValue warnings against the other
    unioned variants and is left as a raw dict. Handle both shapes."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _response_text(response) -> str:
    text_parts = []
    for item in _get(response, "output") or []:
        if _get(item, "type") != "message":
            continue
        for part in _get(item, "content") or []:
            part_text = _get(part, "text")
            if part_text:
                text_parts.append(part_text)
    return "\n".join(text_parts)


def _rate_limit_wait_seconds(e, attempt: int) -> float:
    """Prefer the server's own Retry-After header; fall back to exponential
    backoff (10s, 20s, 40s, ...) if it's absent or unparseable."""
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                pass
    return RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** attempt)


def review(
    evidence: dict,
    top_candidates: list[dict],
    labeled_images: list[tuple[str, str]],
    knowledge_dir: str,
    api_key: str,
    model: str,
    reviewer_name: str,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    """labeled_images: list of (label, image_path). `reviewer_name` is the
    role label (e.g. "claude_sonnet" or the active second-role label) --
    it is threaded into the shared prompt so the model's JSON `reviewer`
    field and this backend's role stay consistent regardless of which
    underlying `model` id is actually called.

    `temperature` and `reasoning_effort` are left unset (API default) unless
    given explicitly. temperature=0 reduces but does not eliminate output
    variance between runs. reasoning_effort (minimal|low|medium|high|xhigh)
    directly controls reasoning-token spend -- the dominant driver of
    anthropic/* models' output-token cost on this endpoint (observed
    6000-8000 reasoning tokens per call at the API's default effort before
    any visible JSON/comment text is produced)."""
    from perplexity import APIStatusError, Perplexity

    client = Perplexity(api_key=api_key)
    system_prompt = build_system_prompt(knowledge_dir)
    user_text = build_user_text(evidence, top_candidates, reviewer_name=reviewer_name)

    content = []
    for label, path in labeled_images:
        content.append({"type": "input_text", "text": f"[Image: {label}]"})
        content.append(_image_content_part(path))
    content.append({"type": "input_text", "text": user_text})

    approx_body_bytes = len(json.dumps(content)) + len(system_prompt)
    if approx_body_bytes > 5_500_000:
        raise RuntimeError(
            f"Assembled Perplexity request is ~{approx_body_bytes / 1e6:.1f}MB, "
            "over the ~5-6MB body-size limit observed to trigger an instant "
            "HTTP 400 from the API. Reduce --top-n or the ambiguity chromosome "
            "list to send fewer images."
        )

    # Only include temperature/reasoning in the call if explicitly set -- the
    # SDK distinguishes "not passed" (Omit, uses the API's own default) from
    # an explicit value, so we must not pass None for either.
    optional_kwargs = {}
    if temperature is not None:
        optional_kwargs["temperature"] = temperature
    if reasoning_effort is not None:
        optional_kwargs["reasoning"] = {"effort": reasoning_effort}

    response = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = client.responses.create(
                model=model,
                instructions=system_prompt,
                input=[{"type": "message", "role": "user", "content": content}],
                max_output_tokens=MAX_OUTPUT_TOKENS,
                stream=False,
                **optional_kwargs,
            )
            break
        except APIStatusError as e:
            if e.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                wait = _rate_limit_wait_seconds(e, attempt)
                print(
                    f"    Perplexity rate limit (429) for model={model!r}, "
                    f"retrying in {wait}s (attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES}) ...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            # Surface the server's actual error body (e.g. "model not found",
            # "payload too large", "unsupported image count") instead of the
            # generic "invalid request" summary the SDK exception __str__ shows.
            body = getattr(e, "body", None) or getattr(getattr(e, "response", None), "text", None)
            raise RuntimeError(
                f"Perplexity API HTTP {e.status_code} for model={model!r}: {body}"
            ) from e

    # response.output_text is unreliable here -- it can come back empty even
    # when response.output[] clearly holds the model's text. Cause: this SDK
    # version's response.output items come back as plain dicts (not
    # attribute-objects) whenever their shape trips a
    # PydanticSerializationUnexpectedValue warning against the other unioned
    # output-item variants, which a normal "message" item does on this Agent
    # API. Pull the text directly from output[] via _response_text() instead
    # of trusting that convenience property.
    text = response.output_text or _response_text(response)

    if not text or not text.strip():
        item_types = [_get(item, "type") or type(item).__name__ for item in (_get(response, "output") or [])]
        dump = None
        for attr in ("model_dump_json", "to_json"):
            if hasattr(response, attr):
                try:
                    dump = getattr(response, attr)()
                except Exception:
                    pass
                break
        raise RuntimeError(
            f"Perplexity returned no output text for model={model!r} "
            f"(status={getattr(response, 'status', None)!r}, "
            f"incomplete_details={getattr(response, 'incomplete_details', None)!r}, "
            f"output_item_types={item_types!r}). "
            f"Full response: {dump if dump else response!r}"
        )
    try:
        return _extract_json(text)
    except json.JSONDecodeError as e:
        # "likely truncated by max_output_tokens" was previously a guess --
        # this branch never actually checked whether the response was
        # reported incomplete. Surface the real status/incomplete_details
        # (same fields the "no output text" branch above already reports)
        # so a short/malformed JSON can be diagnosed instead of assumed.
        raise RuntimeError(
            f"Perplexity output was not valid JSON ({e}). "
            f"status={getattr(response, 'status', None)!r}, "
            f"incomplete_details={getattr(response, 'incomplete_details', None)!r}. "
            f"Output was {len(text)} chars, full text: {text!r}"
        ) from e
