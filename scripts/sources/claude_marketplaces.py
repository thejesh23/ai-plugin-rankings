"""claudemarketplaces.com via Next.js _next/data JSON endpoints.

Strategy: pull buildId from homepage's __NEXT_DATA__ script, then GET the
JSON for each category. The category JSON typically carries a marketplaces
list where each entry has a GitHub URL field."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

import httpx
from bs4 import BeautifulSoup, Tag

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

BASE = "https://claudemarketplaces.com"

CATEGORIES: tuple[str, ...] = (
    "ai-agents", "automation", "backend-api", "blockchain-web",
    "business-finance", "communication", "data-analytics", "database",
    "design-creative", "development", "devops-cloud", "documentation",
    "frontend", "git-version-control", "llm-integration", "mcp-servers",
    "media", "memory-context", "mobile", "productivity", "sales-marketing",
    "scientific-research", "security", "testing-quality",
)

_GH_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)",
)
USER_AGENT = "ai-plugin-rankings-bot/1.0"


def _extract_build_id(homepage_html: str) -> str | None:
    soup = BeautifulSoup(homepage_html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not isinstance(script, Tag) or not script.string:
        return None
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return None
    build_id = data.get("buildId")
    return build_id if isinstance(build_id, str) else None


class ClaudeMarketplacesSource:
    name = "claude_marketplaces"
    default_assistant = "claude-code"

    def __init__(self, base_url: str = BASE) -> None:
        self._base_url = base_url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            try:
                home = c.get("/")
                home.raise_for_status()
            except httpx.HTTPError:
                log.warning("claudemarketplaces home fetch failed")
                return
            build_id = _extract_build_id(home.text)
            if not build_id:
                log.warning("could not find buildId on claudemarketplaces")
                return

            seen: set[str] = set()
            for cat in CATEGORIES:
                path = f"/_next/data/{build_id}/marketplaces/category/{cat}.json"
                try:
                    resp = c.get(path)
                except httpx.HTTPError:
                    log.warning("category fetch failed: %s", cat)
                    continue
                if not resp.is_success:
                    log.warning("category %s returned %d", cat, resp.status_code)
                    continue
                payload = resp.json()
                marketplaces = payload.get("pageProps", {}).get("marketplaces", [])
                for entry in marketplaces:
                    for value in entry.values():
                        if not isinstance(value, str):
                            continue
                        m = _GH_URL_RE.search(value)
                        if not m:
                            continue
                        owner, name = m.group(1), m.group(2).rstrip(".")
                        repo = f"{owner}/{name}"
                        if repo in seen:
                            continue
                        seen.add(repo)
                        yield RawCandidate(
                            repo=repo, source=self.name,
                            hint_assistants=["claude-code"],
                        )
                        break  # only one repo per entry
