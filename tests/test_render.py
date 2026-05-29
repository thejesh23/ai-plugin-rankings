from pathlib import Path

from scripts.models import LatestJson, LatestPlugin, MetadataEntry
from scripts.render import render_all

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"


def _metadata() -> dict[str, MetadataEntry]:
    return {
        "superpowers": MetadataEntry(
            description="Workflow framework with skills",
            tags=["workflow", "skills"], category="productivity",
            enriched_at="2026-05-25T00:00:00Z", readme_sha="x"),
        "cursor-tool": MetadataEntry(
            description="Cursor productivity helper",
            tags=["workflow"], category="productivity",
            enriched_at="2026-05-25T00:00:00Z", readme_sha="x"),
        "multi-target": MetadataEntry(
            description="Cross-assistant utility",
            tags=["automation"], category="productivity",
            enriched_at="2026-05-25T00:00:00Z", readme_sha="x"),
    }


def _load_latest() -> LatestJson:
    return LatestJson.model_validate_json(
        (FIXTURES / "latest-3plugins.json").read_text())


def test_render_matches_golden() -> None:
    output = render_all(_load_latest(), _metadata())
    assert output.readme == (GOLDEN / "README.md").read_text()
    assert output.rankings["all"] == (GOLDEN / "all.md").read_text()
    assert output.rankings["trending"] == (GOLDEN / "trending.md").read_text()
    assert output.rankings["claude-code"] == (GOLDEN / "claude-code.md").read_text()


def test_render_is_deterministic() -> None:
    out1 = render_all(_load_latest(), _metadata())
    out2 = render_all(_load_latest(), _metadata())
    assert out1.readme == out2.readme
    assert out1.rankings == out2.rankings


def test_multi_target_appears_in_each_assistant_file() -> None:
    output = render_all(_load_latest(), _metadata())
    assert "multi-target" in output.rankings["claude-code"]
    assert "multi-target" in output.rankings["cursor"]


def test_missing_metadata_renders_with_em_dash() -> None:
    """A plugin in latest.json but absent from metadata renders with '—'."""
    output = render_all(_load_latest(), {})
    sp_line = [line for line in output.rankings["all"].splitlines() if "superpowers" in line][0]
    assert "—" in sp_line


def test_description_fallback_when_no_metadata() -> None:
    """When metadata is absent but the plugin has a GitHub description, render it."""
    latest = LatestJson(
        generated_at="2026-05-29T00:00:00Z",
        plugins=[LatestPlugin(
            id="x", repo="o/x", assistants=["claude-code"],
            stars=1000, stars_24h=None, stars_7d=None, previous_stars=None,
            archived=False, status="ok",
            url="https://github.com/o/x",
            description="A workflow framework for Claude Code",
        )],
    )
    output = render_all(latest, {})
    row = [line for line in output.rankings["all"].splitlines() if "| 1 |" in line][0]
    assert "A workflow framework for Claude Code" in row


def test_description_fallback_truncates_long_text() -> None:
    """Long descriptions get truncated with ellipsis."""
    long = "x" * 200
    latest = LatestJson(
        generated_at="2026-05-29T00:00:00Z",
        plugins=[LatestPlugin(
            id="x", repo="o/x", assistants=["claude-code"],
            stars=1000, stars_24h=None, stars_7d=None, previous_stars=None,
            archived=False, status="ok",
            url="https://github.com/o/x",
            description=long,
        )],
    )
    output = render_all(latest, {})
    row = [line for line in output.rankings["all"].splitlines() if "| 1 |" in line][0]
    # Truncated body + ellipsis; full 200 chars should not appear
    assert "x" * 200 not in row
    assert "…" in row


def test_description_fallback_escapes_pipes() -> None:
    """Pipe chars in description must be escaped so Markdown table cells aren't broken."""
    latest = LatestJson(
        generated_at="2026-05-29T00:00:00Z",
        plugins=[LatestPlugin(
            id="x", repo="o/x", assistants=["claude-code"],
            stars=1000, stars_24h=None, stars_7d=None, previous_stars=None,
            archived=False, status="ok",
            url="https://github.com/o/x",
            description="Pipe | inside | description",
        )],
    )
    output = render_all(latest, {})
    row = [line for line in output.rankings["all"].splitlines() if "| 1 |" in line][0]
    assert "\\|" in row
