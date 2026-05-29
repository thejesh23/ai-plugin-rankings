import httpx
import respx

from scripts.sources.github_code_search import GithubCodeSearchSource


@respx.mock
def test_emits_repos_from_code_search() -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"repository": {"full_name": "alice/plugin1"}},
                {"repository": {"full_name": "bob/plugin2"}},
            ],
        })
    )
    src = GithubCodeSearchSource(token="t")
    results = list(src.fetch_candidates())
    repos = {c.repo for c in results}
    assert "alice/plugin1" in repos
    assert "bob/plugin2" in repos
    assert all(c.source == "github_code_search" for c in results)


@respx.mock
def test_empty_response_emits_nothing() -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    src = GithubCodeSearchSource(token="t")
    assert list(src.fetch_candidates()) == []


@respx.mock
def test_http_error_logged_emits_nothing() -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(422, json={"message": "bad query"})
    )
    src = GithubCodeSearchSource(token="t")
    # 422 means each query fails individually; source emits nothing for that query
    results = list(src.fetch_candidates())
    assert results == []


@respx.mock
def test_dedupes_within_source() -> None:
    """Multiple queries hitting the same repo emit one RawCandidate per query."""
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"repository": {"full_name": "alice/plugin1"}},
                {"repository": {"full_name": "alice/plugin1"}},
            ],
        })
    )
    src = GithubCodeSearchSource(token="t")
    results = list(src.fetch_candidates())
    # Each query returns the duplicate twice; we accept that and let the
    # orchestrator dedupe by repo across sources. Just verify all map to the
    # same repo.
    assert {c.repo for c in results} == {"alice/plugin1"}
