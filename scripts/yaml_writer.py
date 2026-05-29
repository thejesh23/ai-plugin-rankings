"""Append plugin entries to plugins.yaml while preserving the header comments.

PyYAML strips comments on dump; ruamel.yaml round-trips them. Existing
`scripts/plugins_yaml.py` is read-only and continues to use PyYAML for
validation."""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from scripts.models import PluginEntry

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def append_plugins_to_yaml(path: Path, new_entries: list[PluginEntry]) -> None:
    """Append new_entries to the `plugins` list in the YAML file. No-op if empty."""
    if not new_entries:
        return
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    for entry in new_entries:
        data["plugins"].append({
            "id": entry.id,
            "repo": entry.repo,
            "assistants": entry.assistants,
            "added": entry.added,
        })
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)
