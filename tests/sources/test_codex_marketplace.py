import httpx
import respx

from scripts.sources.codex_marketplace import CodexMarketplaceSource

_FIXTURE_HTML = """
<html><body>
  <a href="https://github.com/alice/codex-thing">Codex Thing</a>
  <a href="https://github.com/bob/claude-plugin">Claude Plugin</a>
  <a href="https://example.com/other">Not GitHub</a>
  <a href="https://github.com/alice/codex-thing">Codex Thing (dup)</a>
</body></html>
"""


@respx.mock
def test_extracts_github_links() -> None:
    respx.get("https://www.codex-marketplace.com/plugins").mock(
        return_value=httpx.Response(200, text=_FIXTURE_HTML)
    )
    src = CodexMarketplaceSource()
    results = list(src.fetch_candidates())
    repos = {c.repo for c in results}
    assert "alice/codex-thing" in repos
    assert "bob/claude-plugin" in repos
    assert all(c.source == "codex_marketplace" for c in results)


@respx.mock
def test_claude_in_name_gets_dual_hint() -> None:
    respx.get("https://www.codex-marketplace.com/plugins").mock(
        return_value=httpx.Response(200, text=_FIXTURE_HTML)
    )
    src = CodexMarketplaceSource()
    by_repo = {c.repo: c for c in src.fetch_candidates()}
    assert by_repo["alice/codex-thing"].hint_assistants == ["codex"]
    assert set(by_repo["bob/claude-plugin"].hint_assistants) == {"codex", "claude-code"}


@respx.mock
def test_failed_fetch_emits_nothing() -> None:
    respx.get("https://www.codex-marketplace.com/plugins").mock(
        return_value=httpx.Response(500)
    )
    src = CodexMarketplaceSource()
    assert list(src.fetch_candidates()) == []
