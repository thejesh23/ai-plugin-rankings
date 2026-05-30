"""Daily orchestrator. Reads plugins.yaml, hits GitHub, writes snapshot,
computes deltas, writes latest.json, renders markdown.

Failure modes:
- 404 on a plugin: mark status=missing, continue
- RateLimitError or unhandled exception: bubble up so the workflow exits
  non-zero. We commit nothing in that case (handled by the workflow itself)."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from scripts.delta import compute_delta
from scripts.github_api import GitHubClient, RepoData, RepoMissingError
from scripts.metadata import load_metadata
from scripts.models import LatestJson, LatestPlugin, SnapshotRow, Status
from scripts.plugins_yaml import load_registry
from scripts.render import render_all
from scripts.snapshot import read_snapshot, snapshot_path, write_snapshot

log = logging.getLogger(__name__)


class _GH(Protocol):
    def fetch_repo(self, repo: str) -> RepoData: ...


def _prev_date(date: str, days: int) -> str:
    d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    return (d - timedelta(days=days)).strftime("%Y-%m-%d")


def _read_prev_snapshot(data_dir: Path, today: str, days_back: int) -> list[SnapshotRow] | None:
    path = snapshot_path(data_dir, _prev_date(today, days_back))
    if not path.exists():
        return None
    return read_snapshot(path)


def run_daily(
    main_dir: Path,
    data_dir: Path,
    gh: GitHubClient | _GH,
    today: str,
) -> None:
    registry = load_registry(main_dir / "plugins.yaml")
    metadata = load_metadata(main_dir / "data" / "metadata.json")

    rows: list[SnapshotRow] = []
    missing_ids: set[str] = set()
    repo_data_by_id: dict[str, RepoData] = {}

    # Track which canonical repo each id ends up at; if a 301 redirect points
    # two different plugin entries at the same canonical repo, keep the first
    # one we saw and mark the later one as a redirect-duplicate.
    canonical_to_id: dict[str, str] = {}
    redirect_dup_ids: set[str] = set()

    for p in registry.plugins:
        try:
            data = gh.fetch_repo(p.repo)
        except RepoMissingError:
            missing_ids.add(p.id)
            continue
        canonical = data.repo.lower()
        if canonical in canonical_to_id:
            log.info(
                "redirect-dup: %s -> %s (already tracked as %s)",
                p.repo, data.repo, canonical_to_id[canonical],
            )
            redirect_dup_ids.add(p.id)
            continue
        canonical_to_id[canonical] = p.id
        repo_data_by_id[p.id] = data
        rows.append(SnapshotRow(
            id=p.id, repo=data.repo, stars=data.stars, forks=data.forks,
            open_issues=data.open_issues, archived=data.archived,
            pushed_at=data.pushed_at,
        ))

    write_snapshot(data_dir, today, rows)

    yesterday_rows = _read_prev_snapshot(data_dir, today, 1)
    week_ago_rows = _read_prev_snapshot(data_dir, today, 7)
    delta_24h = compute_delta(rows, yesterday_rows)
    delta_7d = compute_delta(rows, week_ago_rows)
    prev_by_id = {r.id: r.stars for r in yesterday_rows} if yesterday_rows else {}

    plugins_out: list[LatestPlugin] = []
    for p in registry.plugins:
        if p.id in redirect_dup_ids:
            # Skip silently — the canonical entry is already in plugins_out.
            continue
        if p.id in missing_ids:
            plugins_out.append(LatestPlugin(
                id=p.id, repo=p.repo, assistants=p.assistants,
                stars=0, stars_24h=None, stars_7d=None, previous_stars=None,
                archived=False, status="missing",
                url=f"https://github.com/{p.repo}",
            ))
            continue
        d = repo_data_by_id[p.id]
        status: Status = "archived" if d.archived else "ok"
        plugins_out.append(LatestPlugin(
            id=p.id, repo=d.repo, assistants=p.assistants,
            stars=d.stars, stars_24h=delta_24h.get(p.id),
            stars_7d=delta_7d.get(p.id),
            previous_stars=prev_by_id.get(p.id),
            archived=d.archived, status=status,
            url=f"https://github.com/{d.repo}",
            description=d.description,
        ))

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    latest = LatestJson(generated_at=now_iso, plugins=plugins_out)

    latest_path = main_dir / "data" / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(
        latest.model_dump(), indent=2, sort_keys=True) + "\n")

    missing_path = main_dir / "data" / "missing-plugins.txt"
    if missing_ids:
        missing_path.write_text("\n".join(sorted(missing_ids)) + "\n")
    elif missing_path.exists():
        missing_path.unlink()  # clean up previous day's file if no longer stale

    rendered = render_all(latest, metadata)
    (main_dir / "README.md").write_text(rendered.readme)
    rankings_dir = main_dir / "rankings"
    rankings_dir.mkdir(exist_ok=True)
    for name, body in rendered.rankings.items():
        (rankings_dir / f"{name}.md").write_text(body)


def main() -> None:
    import os
    import sys

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    main_dir = Path(os.environ.get("MAIN_DIR", "."))
    data_dir = Path(os.environ["DATA_DIR"])
    today = os.environ.get("TODAY") or datetime.now(UTC).strftime("%Y-%m-%d")

    client = GitHubClient(token=token)
    try:
        run_daily(main_dir, data_dir, client, today=today)
    finally:
        client.close()


if __name__ == "__main__":
    main()
