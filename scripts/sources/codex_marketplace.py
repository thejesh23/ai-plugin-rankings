"""Scrape codex-marketplace.com/plugins for GitHub repo links."""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import httpx
from bs4 import BeautifulSoup

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

URL = "https://www.codex-marketplace.com/plugins"
_GH_URL_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/?$",
)
USER_AGENT = "ai-plugin-rankings-bot/1.0"


class CodexMarketplaceSource:
    name = "codex_marketplace"
    default_assistant = "codex"

    def __init__(self, url: str = URL) -> None:
        self._url = url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        try:
            resp = httpx.get(self._url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            log.warning("codex-marketplace fetch failed")
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href", ""))
            m = _GH_URL_RE.match(href.rstrip("/"))
            if not m:
                continue
            repo = f"{m.group(1)}/{m.group(2)}"
            if repo in seen:
                continue
            seen.add(repo)
            hints = ["codex"]
            if "claude" in m.group(2).lower():
                hints.append("claude-code")
            yield RawCandidate(
                repo=repo, source=self.name, hint_assistants=hints,
            )
