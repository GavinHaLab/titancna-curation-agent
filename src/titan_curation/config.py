"""Resolve the Perplexity API key, models, and sampling controls.

Precedence for each value: CLI flag > environment variable > config YAML file.
This lets a shared/org key live in a config file while any individual user can
override it with their own personal key via env var or flag, and vice versa.

Both reviewer roles are called through a single PERPLEXITY_API_KEY via
Perplexity's Agent API, using provider/model ids (anthropic/claude-sonnet-5-5,
openai/gpt-5.5 by default). The second role was Gemini
(google/gemini-3.1-pro-preview) until 2026-10-03, swapped out after a
real-data finding: at temperature=0, Gemini's own pick matched itself across
two identical reruns only ~65% of the time (Claude: ~94%), including directly
contradictory numeric readings of the same plot region between runs.
Perplexity's gateway does not expose any image resolution/detail control for
either provider (confirmed empirically -- the `detail` parameter is silently
ignored for both google/* and openai/* models), so the swap was a bet on a
different model/architecture behaving more consistently by default, not on
gaining explicit control.

There was previously also a "direct" backend (bring-your-own Anthropic +
Google keys, bypassing Perplexity) with a separate Claude reviewer
implementation. Removed 2026-10-03 along with Gemini: without Gemini it could
no longer provide two independent reviewers, and it was never actually used
(every real run this tool has done has been via Perplexity) -- Perplexity is
now the only path, which also serves the goal of predictable, standardized
behavior across different people running this tool.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_PERPLEXITY_CLAUDE_MODEL = "anthropic/claude-sonnet-5-5"
# "Second reviewer role" -- deliberately not named after any specific model,
# since this has already been swapped once (Gemini -> GPT-5.5) and may be
# again. Update both this default and PERPLEXITY_SECOND_ROLE_LABEL in cli.py
# together when changing models.
DEFAULT_PERPLEXITY_SECOND_MODEL = "openai/gpt-5.5"


@dataclass
class ReviewerConfig:
    perplexity_api_key: Optional[str] = None
    perplexity_claude_model: str = DEFAULT_PERPLEXITY_CLAUDE_MODEL
    perplexity_second_model: str = DEFAULT_PERPLEXITY_SECOND_MODEL

    # Sampling controls, applied to both reviewer roles. Left unset (None) by
    # default -- the API's own default is used unless the caller explicitly
    # opts in, since temperature=0 reduces but does not eliminate output
    # variance (extended-thinking/reasoning traces and backend routing still
    # introduce some variance even at 0).
    temperature: Optional[float] = None
    # `reasoning.effort`: minimal|low|medium|high|xhigh. Lower effort cuts
    # internal reasoning-token spend -- the dominant driver of output-token
    # cost on this endpoint (observed 0-8000 reasoning tokens per call
    # depending on model/sample).
    reasoning_effort: Optional[str] = None

    def has_claude(self) -> bool:
        return bool(self.perplexity_api_key)

    def has_second_reviewer(self) -> bool:
        return bool(self.perplexity_api_key)


def _load_yaml(path: str) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f) or {}


def resolve_config(
    config_path: Optional[str] = None,
    perplexity_key_flag: Optional[str] = None,
    perplexity_claude_model_flag: Optional[str] = None,
    perplexity_second_model_flag: Optional[str] = None,
    temperature_flag: Optional[float] = None,
    reasoning_effort_flag: Optional[str] = None,
) -> ReviewerConfig:
    file_cfg = {}
    if config_path and os.path.isfile(config_path):
        file_cfg = _load_yaml(config_path)

    perplexity_key = (
        perplexity_key_flag
        or os.environ.get("PERPLEXITY_API_KEY")
        or file_cfg.get("perplexity", {}).get("api_key")
    )
    perplexity_claude_model = (
        perplexity_claude_model_flag
        or os.environ.get("PERPLEXITY_CLAUDE_MODEL")
        or file_cfg.get("perplexity", {}).get("claude_model")
        or DEFAULT_PERPLEXITY_CLAUDE_MODEL
    )
    perplexity_second_model = (
        perplexity_second_model_flag
        or os.environ.get("PERPLEXITY_SECOND_MODEL")
        or file_cfg.get("perplexity", {}).get("second_model")
        or DEFAULT_PERPLEXITY_SECOND_MODEL
    )

    temperature_raw = (
        temperature_flag
        if temperature_flag is not None
        else os.environ.get("TITAN_CURATE_TEMPERATURE")
        or file_cfg.get("temperature")
    )
    temperature = float(temperature_raw) if temperature_raw is not None else None

    reasoning_effort = (
        reasoning_effort_flag
        or os.environ.get("TITAN_CURATE_REASONING_EFFORT")
        or file_cfg.get("reasoning_effort")
    )
    if reasoning_effort is not None and reasoning_effort not in (
        "minimal", "low", "medium", "high", "xhigh",
    ):
        raise ValueError(
            f"Invalid reasoning_effort '{reasoning_effort}': must be one of "
            "minimal, low, medium, high, xhigh"
        )

    return ReviewerConfig(
        perplexity_api_key=perplexity_key,
        perplexity_claude_model=perplexity_claude_model,
        perplexity_second_model=perplexity_second_model,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )
