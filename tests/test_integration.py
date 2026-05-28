"""End-to-end test: feed a fixture plugins.yaml + mocked GitHub responses;
assert all output files exist and contain expected content. This is the
final safety net — if every unit test passes but this one fails, the wiring
between modules is broken."""
import json
import shutil
from pathlib import Path

import httpx
import respx

from scripts.github_api import GitHubClient
from scripts.scrape import run_daily

FIXTURES = Path(__file__).parent / "fixtures"


@respx.mock
def test_full_daily_pipeline(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    shutil.copy(FIXTURES / "integration-plugins.yaml", main_dir / "plugins.yaml")

    def _repo(name: str, stars: int) -> httpx.Response:
        return httpx.Response(200, json={
            "full_name": name, "stargazers_count": stars,
            "forks_count": 1, "open_issues_count": 0, "archived": False,
            "pushed_at": "2026-05-27T00:00:00Z",
        })

    respx.get("https://api.github.com/repos/o/alpha").mock(return_value=_repo("o/alpha", 100))
    respx.get("https://api.github.com/repos/o/beta").mock(return_value=_repo("o/beta", 50))
    respx.get("https://api.github.com/repos/o/gamma").mock(return_value=_repo("o/gamma", 200))

    gh = GitHubClient(token="t")
    try:
        run_daily(main_dir, data_dir, gh, today="2026-05-28")
    finally:
        gh.close()

    assert (main_dir / "README.md").exists()
    assert (main_dir / "data" / "latest.json").exists()
    assert (data_dir / "snapshots" / "2026-05-28.jsonl").exists()
    assert (main_dir / "rankings" / "claude-code.md").exists()
    assert (main_dir / "rankings" / "cursor.md").exists()
    assert (main_dir / "rankings" / "all.md").exists()
    assert (main_dir / "rankings" / "trending.md").exists()

    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    by_id = {p["id"]: p for p in latest["plugins"]}
    assert by_id["alpha"]["stars"] == 100
    assert by_id["gamma"]["stars"] == 200
    assert by_id["alpha"]["stars_24h"] is None

    snapshot_lines = (data_dir / "snapshots" / "2026-05-28.jsonl").read_text().splitlines()
    assert len(snapshot_lines) == 3

    assert "gamma" in (main_dir / "rankings" / "claude-code.md").read_text()
    assert "gamma" in (main_dir / "rankings" / "cursor.md").read_text()
    assert "alpha" not in (main_dir / "rankings" / "cursor.md").read_text()
    assert "beta" not in (main_dir / "rankings" / "claude-code.md").read_text()


@respx.mock
def test_full_pipeline_idempotent(tmp_path: Path) -> None:
    """Running the daily pipeline twice produces the same snapshot file
    and the same rankings markdown."""
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    shutil.copy(FIXTURES / "integration-plugins.yaml", main_dir / "plugins.yaml")

    for name in ("alpha", "beta", "gamma"):
        respx.get(f"https://api.github.com/repos/o/{name}").mock(return_value=httpx.Response(
            200, json={
                "full_name": f"o/{name}", "stargazers_count": 100,
                "forks_count": 0, "open_issues_count": 0, "archived": False,
                "pushed_at": "2026-05-27T00:00:00Z",
            }))

    gh = GitHubClient(token="t")
    try:
        run_daily(main_dir, data_dir, gh, today="2026-05-28")
        snap1 = (data_dir / "snapshots" / "2026-05-28.jsonl").read_bytes()
        all1 = (main_dir / "rankings" / "all.md").read_bytes()

        run_daily(main_dir, data_dir, gh, today="2026-05-28")
        snap2 = (data_dir / "snapshots" / "2026-05-28.jsonl").read_bytes()
        all2 = (main_dir / "rankings" / "all.md").read_bytes()
    finally:
        gh.close()

    assert snap1 == snap2
    assert all1 == all2
