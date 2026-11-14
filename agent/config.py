"""File-backed graph configuration."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_graph_config() -> dict:
    return yaml.safe_load((ROOT / "agent/config.yaml").read_text())
