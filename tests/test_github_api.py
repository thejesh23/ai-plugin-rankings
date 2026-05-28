import httpx
import pytest
import respx

from scripts.github_api import GitHubClient, RateLimitError, RepoData, RepoMissingError


@respx.mock
def test_fetch_repo_success() -> None:
    respx.get("https://api.github.com/repos/obra/superpowers").mock(
        return_value=httpx.Response(200, json={
            "full_name": "obra/superpowers",
            "stargazers_count": 1247,
            "forks_count": 89,
            "open_issues_count": 12,
            "archived": False,
            "pushed_at": "2026-05-27T18:22:00Z",
        })
    )
    client = GitHubClient(token="t")
    data = client.fetch_repo("obra/superpowers")
    assert data == RepoData(
        repo="obra/superpowers", stars=1247, forks=89,
        open_issues=12, archived=False, pushed_at="2026-05-27T18:22:00Z",
    )


@respx.mock
def test_fetch_repo_404_raises_missing() -> None:
    respx.get("https://api.github.com/repos/o/gone").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    client = GitHubClient(token="t")
    with pytest.raises(RepoMissingError):
        client.fetch_repo("o/gone")


@respx.mock
def test_fetch_repo_rate_limit_raises_after_retry() -> None:
    respx.get("https://api.github.com/repos/o/x").mock(
        return_value=httpx.Response(403, json={"message": "rate limit"})
    )
    client = GitHubClient(token="t", max_retries=1, retry_base=0.01)
    with pytest.raises(RateLimitError):
        client.fetch_repo("o/x")


@respx.mock
def test_fetch_repo_500_retries_then_succeeds() -> None:
    route = respx.get("https://api.github.com/repos/o/x")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json={
            "full_name": "o/x", "stargazers_count": 5, "forks_count": 0,
            "open_issues_count": 0, "archived": False,
            "pushed_at": "2026-05-27T00:00:00Z",
        }),
    ]
    client = GitHubClient(token="t", max_retries=3, retry_base=0.01)
    data = client.fetch_repo("o/x")
    assert data.stars == 5


@respx.mock
def test_fetch_readme_returns_text() -> None:
    respx.get("https://api.github.com/repos/o/x/readme").mock(
        return_value=httpx.Response(200, json={
            "encoding": "base64",
            "content": "SGVsbG8gUkVBRE1F",
        })
    )
    client = GitHubClient(token="t")
    assert client.fetch_readme("o/x") == "Hello README"


@respx.mock
def test_fetch_readme_404_returns_none() -> None:
    respx.get("https://api.github.com/repos/o/x/readme").mock(
        return_value=httpx.Response(404)
    )
    client = GitHubClient(token="t")
    assert client.fetch_readme("o/x") is None
