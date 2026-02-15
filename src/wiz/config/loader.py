"""Configuration loader for Wiz."""

from __future__ import annotations

from pathlib import Path

import yaml

from wiz.config.schema import WizConfig


def load_config(path: Path | str | None = None) -> WizConfig:
    """Load configuration from a YAML file.

    If path is None or the file doesn't exist, returns defaults.
    Raises ValueError for malformed YAML.
    """
    if path is None:
        return WizConfig()

    path = Path(path).expanduser().resolve()
    if not path.exists():
        return WizConfig()

    text = path.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML in {path}: {e}") from e

    if data is None or not isinstance(data, dict):
        return WizConfig()

    return WizConfig(**data)
