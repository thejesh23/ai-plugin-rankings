from pathlib import Path

import pytest

from scripts.models import SnapshotRow
from scripts.snapshot import read_snapshot, snapshot_path, write_snapshot

SAMPLE = [
    SnapshotRow(id="a", repo="o/a", stars=10, forks=1, open_issues=0,
                archived=False, pushed_at="2026-05-27T00:00:00Z"),
    SnapshotRow(id="b", repo="o/b", stars=20, forks=2, open_issues=3,
                archived=True, pushed_at="2026-05-26T00:00:00Z"),
]


def test_snapshot_path() -> None:
    base = Path("/tmp/data")
    assert snapshot_path(base, "2026-05-28") == base / "snapshots" / "2026-05-28.jsonl"


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    p = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    assert p.exists()
    loaded = read_snapshot(p)
    assert loaded == SAMPLE


def test_write_is_deterministic(tmp_path: Path) -> None:
    """Writing the same data twice produces byte-identical files."""
    p1 = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    bytes1 = p1.read_bytes()
    p2 = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    bytes2 = p2.read_bytes()
    assert bytes1 == bytes2


def test_read_missing_returns_none(tmp_path: Path) -> None:
    """Missing snapshot is not an error — it just means no history yet."""
    missing = tmp_path / "snapshots" / "1900-01-01.jsonl"
    with pytest.raises(FileNotFoundError):
        read_snapshot(missing)
