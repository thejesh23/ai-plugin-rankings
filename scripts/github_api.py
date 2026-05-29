"""Thin GitHub REST wrapper with retry/backoff."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx


class RateLimitError(Exception):
    """Raised when GitHub returns 403 after retries."""


class RepoMissingError(Exception):
    """Raised when a repo returns 404."""


@dataclass(frozen=True)
class RepoData:
    repo: str
    stars: int
    forks: int
    open_issues: int
    archived: bool
    pushed_at: str
    description: str = ""


class GitHubClient:
    """Synchronous client. One call per repo; no batching required for current scale."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        retry_base: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._retry_base = retry_base

    def fetch_repo(self, repo: str) -> RepoData:
        resp = self._request_with_retry(f"/repos/{repo}")
        if resp.status_code == 404:
            raise RepoMissingError(repo)
        resp.raise_for_status()
        body = resp.json()
        return RepoData(
            repo=body["full_name"],
            stars=body["stargazers_count"],
            forks=body["forks_count"],
            open_issues=body["open_issues_count"],
            archived=body["archived"],
            pushed_at=body["pushed_at"],
            description=body.get("description") or "",
        )

    def fetch_readme(self, repo: str) -> str | None:
        """Returns README text, or None if the repo has no README."""
        resp = self._request_with_retry(f"/repos/{repo}/readme")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        if body.get("encoding") != "base64":
            raise RuntimeError(f"unexpected readme encoding: {body.get('encoding')}")
        return base64.b64decode(body["content"]).decode("utf-8", errors="replace")

    def _request_with_retry(self, path: str) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            resp = self._client.get(path)
            if resp.status_code < 500 and resp.status_code != 403:
                return resp
            last = resp
            if attempt < self._max_retries:
                time.sleep(self._retry_base * (2 ** attempt))
        assert last is not None
        if last.status_code == 403:
            raise RateLimitError(path)
        last.raise_for_status()
        return last  # unreachable

    def close(self) -> None:
        self._client.close()
