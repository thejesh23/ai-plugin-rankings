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
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.github_api import GitHubClient, RepoData, RepoMissingError
from scripts.id_gen import generate_id
from scripts.models import PluginEntry
from scripts.plugins_yaml import load_registry
from scripts.sources.awesome_list import AwesomeListSource
from scripts.sources.base import Source
from scripts.sources.codex_marketplace import CodexMarketplaceSource
from scripts.sources.github_code_search import GithubCodeSearchSource
from scripts.sources.github_topic_search import GithubTopicSearchSource
from scripts.yaml_writer import append_plugins_to_yaml

log = logging.getLogger(__name__)

STAR_THRESHOLD = 1000
KNOWN_ASSISTANTS = {"claude-code", "cursor", "copilot", "codex"}

# The 12 entries added manually before the first discovery run on 2026-05-29.
# These are immune from the purge flow regardless of whether their description
# would pass is_plugin_signal (e.g. obra/superpowers has no assistant marker
# in its description but is unambiguously a Claude Code plugin).
MANUAL_SEED_IDS: frozenset[str] = frozenset({
    "superpowers", "openai-plugins", "claude-mem",
    "alirezarezvani-claude-skills", "claude-octopus", "harness",
    "pg-aiguide", "claude-code-safety-net", "memsearch", "flow-next",
    "dotnet-artisan", "higgsfield-skills",
})

# Words in repo names / descriptions that suggest the repo IS a plugin/skill/
# extension of some kind.
_PLUGIN_NAME_TOKENS = ("plugin", "skill", "extension", "rules", "mcp", "agent")
_PLUGIN_DESC_TOKENS = ("plugin", "skill", "extension", "framework", "rules")
_AGENT_TOKENS = ("agentic", "agent ", "agents ")
_ASSISTANT_MARKERS = ("claude", "cursor", "copilot", "codex")


def is_plugin_signal(repo_name: str, description: str, source: str) -> bool:
    """Return True if the candidate looks like an actual assistant plugin.

    Used by the discovery orchestrator (skip non-plugins) and by purge.py
    (flag existing entries for human review). Passes on ANY of:
      - source is `github_code_search` (manifest filename match — unambiguous)
      - repo name contains plugin/skill/extension/rules/mcp/agent
      - description contains a plugin word AND an assistant marker
      - description contains an "agent(ic)" word AND a plugin word
    """
    if source == "github_code_search":
        return True
    name_lower = repo_name.lower()
    if any(tok in name_lower for tok in _PLUGIN_NAME_TOKENS):
        return True
    desc_lower = description.lower()
    has_plugin_word = any(tok in desc_lower for tok in _PLUGIN_DESC_TOKENS)
    has_assistant = any(tok in desc_lower for tok in _ASSISTANT_MARKERS)
    if has_plugin_word and has_assistant:
        return True
    has_agent_word = any(tok in desc_lower for tok in _AGENT_TOKENS)
    return bool(has_agent_word and has_plugin_word)


# Phrases that suggest a real plugin context (list intros AND product-type
# nouns). Includes "extension/editor/ide/rules" so Cursor descriptions like
# "Cursor editor extension" still match. Excludes bare "for" to avoid false
# positives like "cursor for the database".
_LIST_INTRO_RE = re.compile(
    r"\b(?:works?\s+with|supports?|compatible\s+with|plugin\s+for|"
    r"plugins?\s+for|integrates?\s+with|plugin|extension|editor|ide|rules)\b",
    re.IGNORECASE,
)

# Any of the other three assistant names — used for Cursor co-occurrence check.
_OTHER_ASSISTANT_RE = re.compile(
    r"\b(?:claude(?:\s+code|-code)?|copilot|codex)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Addition:
    repo: str
    data: RepoData
    assistants: list[str]
    via: list[str]


def resolve_assistants(
    data: RepoData, hints: set[str], readme: str | None,
) -> set[str]:
    """Determine which assistants a plugin targets.

    Operates on the GitHub repo description plus any source hints. The
    orchestrator deliberately does NOT pass a readme (see bulk-discovery
    design for the rate-limit rationale); the readme param is kept so unit
    tests can drive specific scenarios."""
    out = {h for h in hints if h in KNOWN_ASSISTANTS}
    text = (data.description or "").lower()

    if "claude code" in text or "claude-code" in text:
        out.add("claude-code")
    if "copilot" in text:
        out.add("copilot")
    if "codex" in text:
        out.add("codex")

    # Cursor: bare match is too ambiguous (DB cursors, mouse cursors, etc.).
    # Tag only if "cursor" appears inside an 80-char window that ALSO
    # contains either a list-intro phrase or another assistant name.
    for m in re.finditer(r"\bcursor\b", text):
        window = text[max(0, m.start() - 80): m.end() + 80]
        if _LIST_INTRO_RE.search(window) or _OTHER_ASSISTANT_RE.search(window):
            out.add("cursor")
            break

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
        # Plugin-quality filter: pass if ANY source/name/description signal
        # indicates this is a real plugin (not just a popular AI tool that
        # happens to be linked from an awesome-* list).
        sources_for_repo = sources_by_repo[repo]
        if not any(
            is_plugin_signal(repo.split("/")[-1], data.description, s)
            for s in sources_for_repo
        ):
            log.warning("non-plugin signal for %s; skipping", repo)
            continue
        # Resolve from hints + description only; skipping fetch_readme halves
        # API calls per candidate and keeps us inside the 5000/hr budget when
        # thousands of candidates are surfaced.
        assistants = resolve_assistants(data, hints_by_repo[repo], readme=None)
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
        # claudemarketplaces.com removed 2026-05-29 — they switched to fully
        # dynamic SSR (no __NEXT_DATA__ in homepage HTML, no buildId to
        # scrape). Would need a headless browser to ingest.
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
