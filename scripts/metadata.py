"""metadata.json holds LLM-generated descriptions/tags per plugin.
Refreshed weekly; daily job reads it but does not modify."""
import json
from pathlib import Path

from scripts.models import MetadataEntry


def load_metadata(path: Path) -> dict[str, MetadataEntry]:
    """Returns {} if the file doesn't exist (first run)."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: MetadataEntry.model_validate(v) for k, v in raw.items()}


def save_metadata(path: Path, data: dict[str, MetadataEntry]) -> None:
    """Save with sorted keys and consistent indentation so git diffs are clean."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {k: data[k].model_dump() for k in sorted(data.keys())}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)
