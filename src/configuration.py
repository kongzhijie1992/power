"""Configuration utilities for reproducible pipeline runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")
DEFAULT_EXAMPLE_PATH = Path(__file__).with_name("config.yaml.example")


def _resolve_default_config_path() -> Path:
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return DEFAULT_EXAMPLE_PATH


def load_yaml_config(config_path: Path | str | None = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path is not None else _resolve_default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_value(raw: str) -> Any:
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def apply_overrides(config: Dict[str, Any], overrides: Iterable[str]) -> Dict[str, Any]:
    updated = dict(config)
    for override in overrides:
        if "=" not in override:
            raise ValueError(
                f"Override '{override}' must be in key=value format (use dot notation)."
            )
        key, raw_value = override.split("=", 1)
        value = _parse_value(raw_value)
        cursor: Dict[str, Any] = updated
        parts = [part for part in key.split(".") if part]
        if not parts:
            raise ValueError(f"Override '{override}' has no key path.")
        for part in parts[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                cursor[part] = {}
            cursor = cursor[part]
        cursor[parts[-1]] = value
    return updated


def load_config_with_overrides(
    config_path: Path | str | None = None, overrides: Iterable[str] | None = None
) -> Dict[str, Any]:
    cfg = load_yaml_config(config_path)
    if overrides:
        cfg = apply_overrides(cfg, overrides)
    return cfg
