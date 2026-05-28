from pathlib import Path

from scripts.metadata import load_metadata, save_metadata
from scripts.models import MetadataEntry

ENTRY = MetadataEntry(
    description="A tool",
    tags=["workflow", "skills"],
    category="productivity",
    enriched_at="2026-05-25T00:00:00Z",
    readme_sha="abc123",
)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    save_metadata(path, {"superpowers": ENTRY})
    loaded = load_metadata(path)
    assert loaded == {"superpowers": ENTRY}


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_metadata(tmp_path / "absent.json") == {}


def test_save_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    save_metadata(path, {"b": ENTRY, "a": ENTRY})
    b1 = path.read_bytes()
    save_metadata(path, {"a": ENTRY, "b": ENTRY})
    b2 = path.read_bytes()
    assert b1 == b2  # keys sorted on save
