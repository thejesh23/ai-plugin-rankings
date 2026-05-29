"""Multi-source discovery orchestrator.

Aggregates candidates from all configured sources, dedupes by repo, fetches
canonical star counts via the GitHub API, applies the >=1000-star +
non-archived filter, resolves multi-assistant tags by hint + README grep,
generates slug IDs, appends new entries to plugins.yaml (preserving header
comments via ruamel.yaml), writes an audit line to discovery.log, and exits.

Designed for the weekly cron. The workflow itself does the git
add+commit+push after this script returns successfully."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.github_api import GitHubClient, RepoData, RepoMissingError
from scripts.id_gen import generate_id
from scripts.models import PluginEntry
from scripts.plugins_yaml import load_registry
from scripts.sources.awesome_list import AwesomeListSource
from scripts.sources.base import Source
from scripts.sources.claude_marketplaces import ClaudeMarketplacesSource
from scripts.sources.codex_marketplace import CodexMarketplaceSource
from scripts.sources.github_code_search import GithubCodeSearchSource
from scripts.sources.github_topic_search import GithubTopicSearchSource
from scripts.yaml_writer import append_plugins_to_yaml

log = logging.getLogger(__name__)

STAR_THRESHOLD = 1000
KNOWN_ASSISTANTS = {"claude-code", "cursor", "copilot", "codex"}


@dataclass(frozen=True)
class Addition:
    repo: str
    data: RepoData
    assistants: list[str]
    via: list[str]


def resolve_assistants(
    data: RepoData, hints: set[str], readme: str | None,
) -> set[str]:
    out = {h for h in hints if h in KNOWN_ASSISTANTS}
    text = ((data.description or "") + " " + (readme or ""))[:5_000].lower()
    if "claude code" in text or "claude-code" in text:
        out.add("claude-code")
    if "cursor" in text and any(
        k in text for k in ("editor", "ide", "rules", "extension")
    ):
        out.add("cursor")
    if "github copilot" in text or "copilot extension" in text:
        out.add("copilot")
    if "codex cli" in text or "openai codex" in text:
        out.add("codex")
    return out


def _append_log_lines(log_path: Path, lines: list[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def run_discover(
    plugins_yaml: Path,
    discovery_log: Path,
    sources: list[Source],
    gh: GitHubClient,
    today: str,
    disabled: set[str],
) -> list[Addition]:
    registry = load_registry(plugins_yaml)
    known_repos = {p.repo.lower() for p in registry.plugins}

    hints_by_repo: dict[str, set[str]] = {}
    sources_by_repo: dict[str, set[str]] = {}

    for source in sources:
        if source.name in disabled:
            log.info("source %s disabled; skipping", source.name)
            continue
        try:
            for raw in source.fetch_candidates():
                if raw.repo.lower() in known_repos:
                    continue
                hints_by_repo.setdefault(raw.repo, set()).update(raw.hint_assistants)
                sources_by_repo.setdefault(raw.repo, set()).add(raw.source)
        except Exception:
            log.exception("source %s failed; continuing", source.name)

    additions: list[Addition] = []
    for repo in sorted(hints_by_repo.keys()):
        try:
            data = gh.fetch_repo(repo)
        except RepoMissingError:
            continue
        if data.stars < STAR_THRESHOLD or data.archived:
            continue
        try:
            readme = gh.fetch_readme(repo)
        except Exception:
            log.warning("could not fetch README for %s", repo)
            readme = None
        assistants = resolve_assistants(data, hints_by_repo[repo], readme)
        if not assistants:
            log.warning("no assistants resolved for %s; skipping", repo)
            continue
        additions.append(Addition(
            repo=repo, data=data,
            assistants=sorted(assistants),
            via=sorted(sources_by_repo[repo]),
        ))

    if not additions:
        return []

    existing_ids = {p.id for p in registry.plugins}
    new_entries: list[PluginEntry] = []
    log_lines: list[str] = []
    for addition in additions:
        slug = generate_id(addition.repo, existing_ids)
        existing_ids.add(slug)
        new_entries.append(PluginEntry(
            id=slug, repo=addition.repo,
            assistants=addition.assistants, added=today,
        ))
        log_lines.append(
            f"{today}  {addition.repo}  {addition.data.stars} stars  "
            f"via={','.join(addition.via)}  "
            f"assistants={','.join(addition.assistants)}"
        )

    append_plugins_to_yaml(plugins_yaml, new_entries)
    _append_log_lines(discovery_log, log_lines)
    return additions


def main() -> None:
    import sys

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    disabled = {
        s.strip() for s in os.environ.get("DISABLED_SOURCES", "").split(",")
        if s.strip()
    }
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    gh = GitHubClient(token=token)
    sources: list[Source] = [
        GithubCodeSearchSource(token=token),
        GithubTopicSearchSource(token=token),
        AwesomeListSource(token=token),
        ClaudeMarketplacesSource(),
        CodexMarketplaceSource(),
    ]
    try:
        run_discover(
            plugins_yaml=Path("plugins.yaml"),
            discovery_log=Path("discovery.log"),
            sources=sources,
            gh=gh,
            today=today,
            disabled=disabled,
        )
    finally:
        gh.close()


if __name__ == "__main__":
    main()
