import httpx
import respx

from scripts.sources.claude_marketplaces import ClaudeMarketplacesSource

_HOMEPAGE_HTML = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"buildId":"ABC123","props":{}}
</script>
</body></html>
"""

_CATEGORY_JSON_AI_AGENTS = {
    "pageProps": {
        "marketplaces": [
            {"github": "https://github.com/alice/aagent"},
            {"github": "https://github.com/bob/orch"},
        ],
    },
}


@respx.mock
def test_uses_buildid_to_fetch_categories() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text=_HOMEPAGE_HTML)
    )
    respx.get(
        "https://claudemarketplaces.com/_next/data/ABC123/marketplaces/category/ai-agents.json"
    ).mock(return_value=httpx.Response(200, json=_CATEGORY_JSON_AI_AGENTS))
    respx.get(
        url__regex=r"https://claudemarketplaces\.com/_next/data/ABC123/marketplaces/category/.+\.json"
    ).mock(return_value=httpx.Response(200, json={"pageProps": {"marketplaces": []}}))

    src = ClaudeMarketplacesSource()
    results = list(src.fetch_candidates())
    assert {c.repo for c in results} == {"alice/aagent", "bob/orch"}
    assert all(c.source == "claude_marketplaces" for c in results)
    assert all(c.hint_assistants == ["claude-code"] for c in results)


@respx.mock
def test_missing_buildid_emits_nothing() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text="<html><body>no script</body></html>")
    )
    src = ClaudeMarketplacesSource()
    assert list(src.fetch_candidates()) == []


@respx.mock
def test_category_404_skipped_others_continue() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text=_HOMEPAGE_HTML)
    )
    respx.get(
        "https://claudemarketplaces.com/_next/data/ABC123/marketplaces/category/ai-agents.json"
    ).mock(return_value=httpx.Response(404))
    respx.get(
        url__regex=r"https://claudemarketplaces\.com/_next/data/ABC123/marketplaces/category/.+\.json"
    ).mock(return_value=httpx.Response(200, json={"pageProps": {
        "marketplaces": [{"github": "https://github.com/x/y"}],
    }}))
    src = ClaudeMarketplacesSource()
    repos = {c.repo for c in src.fetch_candidates()}
    assert repos == {"x/y"}
