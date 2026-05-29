import httpx
import respx

from scripts.sources.github_topic_search import GithubTopicSearchSource


@respx.mock
def test_emits_repos_from_topic_search() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"full_name": "alice/p1"},
                {"full_name": "bob/p2"},
            ],
        })
    )
    src = GithubTopicSearchSource(token="t")
    results = list(src.fetch_candidates())
    assert {c.repo for c in results} >= {"alice/p1", "bob/p2"}
    assert all(c.source == "github_topic_search" for c in results)


@respx.mock
def test_each_query_uses_correct_hint() -> None:
    """Hint set should equal the set of distinct hints declared in _QUERIES."""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={"items": [{"full_name": "x/y"}]})
    )
    src = GithubTopicSearchSource(token="t")
    by_hint: dict[str, set[str]] = {}
    for c in src.fetch_candidates():
        for h in c.hint_assistants:
            by_hint.setdefault(h, set()).add(c.repo)
    assert by_hint.keys() == {h for _, h in src._QUERIES}


@respx.mock
def test_empty_response_emits_nothing() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    src = GithubTopicSearchSource(token="t")
    assert list(src.fetch_candidates()) == []
