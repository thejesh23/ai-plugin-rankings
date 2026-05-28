
import httpx
import respx

from scripts.discover import Candidate, find_candidates


@respx.mock
def test_find_candidates_filters_known_and_small() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {
                    "full_name": "obra/superpowers", "stargazers_count": 1000,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "known",
                },
                {
                    "full_name": "tiny/x", "stargazers_count": 3,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "tiny",
                },
                {
                    "full_name": "old/y", "stargazers_count": 500,
                    "archived": True, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "archived",
                },
                {
                    "full_name": "newco/cool-plugin", "stargazers_count": 200,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "Cool",
                },
            ],
        })
    )
    known = {"obra/superpowers"}
    candidates = find_candidates(
        token="t",
        queries=["topic:claude-code-plugin"],
        known_repos=known,
        min_stars=10,
        max_age_days=365,
        today="2026-05-28",
    )
    assert candidates == [Candidate(
        repo="newco/cool-plugin", stars=200,
        description="Cool", assistant_guess="claude-code")]


@respx.mock
def test_find_candidates_skips_stale() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [{
                "full_name": "stale/x", "stargazers_count": 100,
                "archived": False, "pushed_at": "2024-01-01T00:00:00Z",
                "description": "old",
            }],
        })
    )
    candidates = find_candidates(
        token="t",
        queries=["topic:cursor-extension"],
        known_repos=set(), min_stars=10, max_age_days=365,
        today="2026-05-28",
    )
    assert candidates == []
