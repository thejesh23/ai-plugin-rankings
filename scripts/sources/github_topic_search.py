"""Expanded GitHub topic + in:name search for AI assistant plugins."""
from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)


class GithubTopicSearchSource:
    name = "github_topic_search"
    default_assistant = "claude-code"

    _QUERIES: tuple[tuple[str, str], ...] = (
        ("topic:claude-code-plugin", "claude-code"),
        ("topic:claude-skills", "claude-code"),
        ("topic:claude-code", "claude-code"),
        ("topic:cursor-rules", "cursor"),
        ("topic:cursor-extension", "cursor"),
        ("topic:cursorrules", "cursor"),
        ("topic:copilot-extension", "copilot"),
        ("topic:github-copilot-extension", "copilot"),
        ("topic:codex-plugin", "codex"),
        ("topic:codex-extension", "codex"),
        ("topic:mcp-server", "claude-code"),
        ("in:name claude-code stars:>10", "claude-code"),
        ("in:name cursor-rules stars:>10", "cursor"),
    )

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            for query, hint in self._QUERIES:
                try:
                    resp = c.get(
                        "/search/repositories",
                        params={"q": query, "per_page": 100},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    log.warning("topic search query failed: %r", query)
                    continue
                for item in resp.json().get("items", []):
                    yield RawCandidate(
                        repo=item["full_name"],
                        source=self.name,
                        hint_assistants=[hint],
                    )
