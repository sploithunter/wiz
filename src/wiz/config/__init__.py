"""Configuration system for Wiz."""

from wiz.config.loader import load_config
from wiz.config.schema import WizConfig

__all__ = ["load_config", "WizConfig"]
