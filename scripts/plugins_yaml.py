from pathlib import Path

import yaml

from scripts.models import PluginRegistry


def load_registry(path: Path) -> PluginRegistry:
    """Load and validate plugins.yaml. Raises FileNotFoundError on missing
    file, ValidationError on schema violations."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return PluginRegistry.model_validate(raw)
