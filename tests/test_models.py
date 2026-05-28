import pytest
from pydantic import ValidationError

from scripts.models import (
    LatestPlugin,
    MetadataEntry,
    PluginEntry,
    PluginRegistry,
    SnapshotRow,
)


def test_plugin_entry_valid() -> None:
    p = PluginEntry(
        id="superpowers", repo="obra/superpowers",
        assistants=["claude-code"], added="2026-05-28",
    )
    assert p.id == "superpowers"
    assert p.assistants == ["claude-code"]


def test_plugin_entry_rejects_unknown_assistant() -> None:
    with pytest.raises(ValidationError):
        PluginEntry(
            id="x", repo="o/x", assistants=["windsurf"], added="2026-05-28",
        )


def test_plugin_entry_rejects_bad_repo_format() -> None:
    with pytest.raises(ValidationError):
        PluginEntry(
            id="x", repo="not-a-slash-pair", assistants=["cursor"], added="2026-05-28",
        )


def test_plugin_registry_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        PluginRegistry(plugins=[
            PluginEntry(id="a", repo="o/a", assistants=["cursor"], added="2026-05-28"),
            PluginEntry(id="a", repo="o/b", assistants=["cursor"], added="2026-05-28"),
        ])


def test_metadata_entry_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        MetadataEntry(
            description="x", tags=["workflow"], category="not-a-category",  # type: ignore[arg-type]
            enriched_at="2026-05-25T00:00:00Z", readme_sha="abc",
        )


def test_snapshot_row_roundtrip() -> None:
    row = SnapshotRow(
        id="x", repo="o/x", stars=100, forks=10,
        open_issues=5, archived=False, pushed_at="2026-05-27T00:00:00Z",
    )
    assert row.model_dump()["stars"] == 100


def test_latest_plugin_status_enum() -> None:
    with pytest.raises(ValidationError):
        LatestPlugin(
            id="x", repo="o/x", assistants=["cursor"], stars=1,
            stars_24h=0, stars_7d=0, previous_stars=1, archived=False,
            status="weird",  # type: ignore[arg-type]
            url="https://github.com/o/x",
        )
