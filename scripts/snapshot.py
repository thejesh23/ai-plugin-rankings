"""Snapshot files live on the orphan `data` branch.
One file per day, one line per plugin (JSONL). Idempotent overwrite."""
import json
from collections.abc import Iterable
from pathlib import Path

from scripts.models import SnapshotRow


def snapshot_path(data_dir: Path, date: str) -> Path:
    return data_dir / "snapshots" / f"{date}.jsonl"


def write_snapshot(data_dir: Path, date: str, rows: Iterable[SnapshotRow]) -> Path:
    """Write a snapshot atomically. Idempotent: same input → same bytes."""
    rows_sorted = sorted(rows, key=lambda r: r.id)
    path = snapshot_path(data_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows_sorted:
            # sort_keys=True ensures byte-determinism across Python runs.
            f.write(json.dumps(row.model_dump(), sort_keys=True, separators=(",", ":")))
            f.write("\n")
    tmp.replace(path)
    return path


def read_snapshot(path: Path) -> list[SnapshotRow]:
    """Read a snapshot. Raises FileNotFoundError if absent."""
    with path.open("r", encoding="utf-8") as f:
        return [SnapshotRow.model_validate_json(line) for line in f if line.strip()]
