import json
from pathlib import Path
from unittest.mock import MagicMock

from scripts.github_api import RepoData, RepoMissingError
from scripts.models import SnapshotRow
from scripts.scrape import run_daily
from scripts.snapshot import write_snapshot


def _yesterday_snapshot(data_dir: Path) -> None:
    write_snapshot(data_dir, "2026-05-27", [
        SnapshotRow(id="a", repo="o/a", stars=90, forks=1, open_issues=0,
                    archived=False, pushed_at="2026-05-26T00:00:00Z"),
    ])


def test_daily_run_writes_snapshot_and_latest(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: a
    repo: o/a
    assistants: [cursor]
    added: "2026-05-28"
""")
    _yesterday_snapshot(data_dir)

    gh = MagicMock()
    gh.fetch_repo.return_value = RepoData(
        repo="o/a", stars=100, forks=2, open_issues=3,
        archived=False, pushed_at="2026-05-27T18:00:00Z")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    snapshot_path = data_dir / "snapshots" / "2026-05-28.jsonl"
    assert snapshot_path.exists()
    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    assert latest["plugins"][0]["stars"] == 100
    assert latest["plugins"][0]["stars_24h"] == 10


def test_daily_run_marks_missing_plugin(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: ghost
    repo: o/ghost
    assistants: [cursor]
    added: "2026-05-28"
""")
    gh = MagicMock()
    gh.fetch_repo.side_effect = RepoMissingError("o/ghost")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    assert latest["plugins"][0]["status"] == "missing"


def test_daily_run_renders_readme_and_rankings(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: a
    repo: o/a
    assistants: [cursor]
    added: "2026-05-28"
""")
    gh = MagicMock()
    gh.fetch_repo.return_value = RepoData(
        repo="o/a", stars=10, forks=0, open_issues=0,
        archived=False, pushed_at="2026-05-27T00:00:00Z")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    assert (main_dir / "README.md").exists()
    assert (main_dir / "rankings" / "cursor.md").exists()
    assert (main_dir / "rankings" / "all.md").exists()
