"""GitHub code search for plugin manifest filenames.

Searches for files that are distinctive to each ecosystem (e.g.
`.claude-plugin.json`, `.cursorrules`). Code search rate limit is 30/min
which is fine at 7 queries/week."""
from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)


class GithubCodeSearchSource:
    name = "github_code_search"
    default_assistant = "claude-code"

    _QUERIES: tuple[tuple[str, str], ...] = (
        ("filename:.claude-plugin.json", "claude-code"),
        ("filename:claude-plugin.json", "claude-code"),
        ("filename:.cursorrules", "cursor"),
        ("filename:cursor.json path:.cursor", "cursor"),
        ("filename:codex-plugin.toml", "codex"),
        ("filename:codex.toml", "codex"),
        ("filename:copilot-extension.json", "copilot"),
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
                    resp = c.get("/search/code", params={"q": query, "per_page": 100})
                    resp.raise_for_status()
                except httpx.HTTPError:
                    log.warning("code search query failed: %r", query)
                    continue
                for item in resp.json().get("items", []):
                    repo = item["repository"]["full_name"]
                    yield RawCandidate(
                        repo=repo, source=self.name, hint_assistants=[hint],
                    )
