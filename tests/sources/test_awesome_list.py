import base64

import httpx
import respx

from scripts.sources.awesome_list import AwesomeListSource


def _b64_readme(text: str) -> dict[str, str]:
    return {
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
    }


@respx.mock
def test_extracts_github_links_from_readme() -> None:
    body = """
    # Awesome Claude Plugins

    - [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) — desc
    - [obra/superpowers](https://github.com/obra/superpowers) — workflow framework
    - Not a GitHub link: https://example.com/foo
    """
    respx.get(
        "https://api.github.com/repos/ComposioHQ/awesome-claude-plugins/readme"
    ).mock(return_value=httpx.Response(200, json=_b64_readme(body)))

    src = AwesomeListSource(
        token="t",
        lists=[("ComposioHQ/awesome-claude-plugins", "claude-code")],
    )
    results = list(src.fetch_candidates())
    assert {c.repo for c in results} == {
        "thedotmack/claude-mem", "obra/superpowers",
    }
    assert all(c.source == "awesome_list" for c in results)
    assert all(c.hint_assistants == ["claude-code"] for c in results)


@respx.mock
def test_excludes_self_reference() -> None:
    body = """
    # Awesome Claude Plugins
    Self: https://github.com/ComposioHQ/awesome-claude-plugins
    - https://github.com/x/y
    """
    respx.get(
        "https://api.github.com/repos/ComposioHQ/awesome-claude-plugins/readme"
    ).mock(return_value=httpx.Response(200, json=_b64_readme(body)))

    src = AwesomeListSource(
        token="t",
        lists=[("ComposioHQ/awesome-claude-plugins", "claude-code")],
    )
    repos = {c.repo for c in src.fetch_candidates()}
    assert "ComposioHQ/awesome-claude-plugins" not in repos
    assert "x/y" in repos


@respx.mock
def test_missing_readme_skipped() -> None:
    respx.get(
        "https://api.github.com/repos/o/x/readme"
    ).mock(return_value=httpx.Response(404))
    src = AwesomeListSource(token="t", lists=[("o/x", "claude-code")])
    assert list(src.fetch_candidates()) == []
