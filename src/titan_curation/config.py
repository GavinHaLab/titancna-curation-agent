"""Resolve API keys, models, and reviewer backend.

Precedence for each value: CLI flag > environment variable > config YAML file.
This lets a shared/org key live in a config file while any individual user can
override it with their own personal key via env var or flag, and vice versa.

Two reviewer backends are supported, selectable independently of which keys
happen to be set:

- "direct": call Anthropic and Google APIs directly with ANTHROPIC_API_KEY /
  GEMINI_API_KEY (the original design).
- "perplexity": call BOTH reviewer roles through a single PERPLEXITY_API_KEY
  via Perplexity's Agent API, using provider/model ids
  (anthropic/claude-sonnet-5, google/gemini-3.1-pro-preview by default).

"auto" (the default) picks "perplexity" if PERPLEXITY_API_KEY is set, else
falls back to "direct".
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro"

DEFAULT_PERPLEXITY_CLAUDE_MODEL = "anthropic/claude-sonnet-5"
DEFAULT_PERPLEXITY_GEMINI_MODEL = "google/gemini-3.1-pro-preview"


@dataclass
class ReviewerConfig:
    backend: str = "auto"  # "auto" | "direct" | "perplexity"

    anthropic_api_key: Optional[str] = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    gemini_api_key: Optional[str] = None
    gemini_model: str = DEFAULT_GEMINI_MODEL

    perplexity_api_key: Optional[str] = None
    perplexity_claude_model: str = DEFAULT_PERPLEXITY_CLAUDE_MODEL
    perplexity_gemini_model: str = DEFAULT_PERPLEXITY_GEMINI_MODEL

    def resolved_backend(self) -> str:
        if self.backend == "perplexity":
            return "perplexity"
        if self.backend == "direct":
            return "direct"
        # auto
        return "perplexity" if self.perplexity_api_key else "direct"

    def has_claude(self) -> bool:
        if self.resolved_backend() == "perplexity":
            return bool(self.perplexity_api_key)
        return bool(self.anthropic_api_key)

    def has_gemini(self) -> bool:
        if self.resolved_backend() == "perplexity":
            return bool(self.perplexity_api_key)
        return bool(self.gemini_api_key)


def _load_yaml(path: str) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f) or {}


def resolve_config(
    config_path: Optional[str] = None,
    anthropic_key_flag: Optional[str] = None,
    gemini_key_flag: Optional[str] = None,
    anthropic_model_flag: Optional[str] = None,
    gemini_model_flag: Optional[str] = None,
    backend_flag: Optional[str] = None,
    perplexity_key_flag: Optional[str] = None,
    perplexity_claude_model_flag: Optional[str] = None,
    perplexity_gemini_model_flag: Optional[str] = None,
) -> ReviewerConfig:
    file_cfg = {}
    if config_path and os.path.isfile(config_path):
        file_cfg = _load_yaml(config_path)

    anthropic_key = (
        anthropic_key_flag
        or os.environ.get("ANTHROPIC_API_KEY")
        or file_cfg.get("anthropic", {}).get("api_key")
    )
    gemini_key = (
        gemini_key_flag
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or file_cfg.get("gemini", {}).get("api_key")
    )
    anthropic_model = (
        anthropic_model_flag
        or os.environ.get("ANTHROPIC_MODEL")
        or file_cfg.get("anthropic", {}).get("model")
        or DEFAULT_ANTHROPIC_MODEL
    )
    gemini_model = (
        gemini_model_flag
        or os.environ.get("GEMINI_MODEL")
        or file_cfg.get("gemini", {}).get("model")
        or DEFAULT_GEMINI_MODEL
    )

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
    perplexity_gemini_model = (
        perplexity_gemini_model_flag
        or os.environ.get("PERPLEXITY_GEMINI_MODEL")
        or file_cfg.get("perplexity", {}).get("gemini_model")
        or DEFAULT_PERPLEXITY_GEMINI_MODEL
    )
    backend = (
        backend_flag
        or os.environ.get("TITAN_CURATE_BACKEND")
        or file_cfg.get("backend")
        or "auto"
    )
    if backend not in ("auto", "direct", "perplexity"):
        raise ValueError(f"Invalid backend '{backend}': must be auto, direct, or perplexity")

    return ReviewerConfig(
        backend=backend,
        anthropic_api_key=anthropic_key,
        anthropic_model=anthropic_model,
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        perplexity_api_key=perplexity_key,
        perplexity_claude_model=perplexity_claude_model,
        perplexity_gemini_model=perplexity_gemini_model,
    )
