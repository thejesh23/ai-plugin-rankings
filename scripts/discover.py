"""Weekly candidate discovery.

Queries GitHub Search for repos matching plugin-shaped patterns; filters by
star count, archive status, and recency. Output is a list of Candidate
objects that the workflow turns into PR body content. Discovery NEVER
auto-adds to plugins.yaml — every entry must pass human review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

QUERY_TO_ASSISTANT: dict[str, str] = {
    "topic:claude-code-plugin": "claude-code",
    "topic:cursor-extension": "cursor",
    "topic:copilot-extension": "copilot",
    "topic:codex-plugin": "codex",
}


@dataclass(frozen=True)
class Candidate:
    repo: str
    stars: int
    description: str
    assistant_guess: str


def _too_stale(pushed_at: str, today: str, max_age_days: int) -> bool:
    pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    today_dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (today_dt - pushed) > timedelta(days=max_age_days)


def find_candidates(
    token: str,
    queries: list[str],
    known_repos: set[str],
    min_stars: int,
    max_age_days: int,
    today: str,
) -> list[Candidate]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    out: list[Candidate] = []
    seen: set[str] = set()
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30) as c:
        for q in queries:
            resp = c.get("/search/repositories", params={"q": q, "per_page": 50})
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                repo = item["full_name"]
                if repo in known_repos or repo in seen:
                    continue
                if item["stargazers_count"] < min_stars:
                    continue
                if item["archived"]:
                    continue
                if _too_stale(item["pushed_at"], today, max_age_days):
                    continue
                seen.add(repo)
                out.append(Candidate(
                    repo=repo,
                    stars=item["stargazers_count"],
                    description=item.get("description") or "",
                    assistant_guess=QUERY_TO_ASSISTANT.get(q, "claude-code"),
                ))
    return out


def render_candidate_pr_body(candidates: list[Candidate]) -> str:
    """Markdown body for the discovery PR."""
    if not candidates:
        return "No new candidates this week.\n"
    lines = ["Found the following candidates. Move accepted entries into `plugins.yaml`.\n"]
    for c in sorted(candidates, key=lambda x: -x.stars):
        lines.append(
            f"- **{c.repo}** ({c.stars} stars) — _guess: {c.assistant_guess}_  \n"
            f"  {c.description}\n"
        )
    return "\n".join(lines)
