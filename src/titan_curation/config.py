"""Resolve API keys and model names.

Precedence for each provider: CLI flag > environment variable > config YAML file.
This lets a shared/org key live in a config file while any individual user can
override it with their own personal key via env var or flag, and vice versa.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro"


@dataclass
class ReviewerConfig:
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    gemini_api_key: Optional[str] = None
    gemini_model: str = DEFAULT_GEMINI_MODEL

    def has_claude(self) -> bool:
        return bool(self.anthropic_api_key)

    def has_gemini(self) -> bool:
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

    return ReviewerConfig(
        anthropic_api_key=anthropic_key,
        anthropic_model=anthropic_model,
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
    )
