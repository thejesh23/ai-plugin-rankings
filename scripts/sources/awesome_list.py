"""Parse READMEs of curated awesome-* lists; extract every github.com link."""
from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

DEFAULT_LISTS: list[tuple[str, str]] = [
    ("ComposioHQ/awesome-claude-plugins", "claude-code"),
    ("ccplugins/awesome-claude-code-plugins", "claude-code"),
    ("quemsah/awesome-claude-plugins", "claude-code"),
]

_GH_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)",
)


class AwesomeListSource:
    name = "awesome_list"
    default_assistant = "claude-code"

    def __init__(
        self,
        token: str,
        lists: list[tuple[str, str]] | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._lists = lists if lists is not None else DEFAULT_LISTS

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            for list_repo, hint in self._lists:
                try:
                    resp = c.get(f"/repos/{list_repo}/readme")
                except httpx.HTTPError:
                    log.warning("could not fetch %s", list_repo)
                    continue
                if resp.status_code == 404:
                    log.warning("no README for %s", list_repo)
                    continue
                if not resp.is_success:
                    log.warning("readme fetch failed for %s: %d", list_repo, resp.status_code)
                    continue
                body = resp.json()
                if body.get("encoding") != "base64":
                    continue
                text = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
                seen: set[str] = set()
                for m in _GH_URL_RE.finditer(text):
                    owner, name = m.group(1), m.group(2)
                    name = name.rstrip(".")
                    repo = f"{owner}/{name}"
                    if repo == list_repo:
                        continue
                    if repo in seen:
                        continue
                    seen.add(repo)
                    yield RawCandidate(
                        repo=repo, source=self.name, hint_assistants=[hint],
                    )
