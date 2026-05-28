import json
from pathlib import Path

from scripts.models import LatestJson, MetadataEntry
from scripts.render import render_all, RenderOutput


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
    sp_line = [l for l in output.rankings["all"].splitlines() if "superpowers" in l][0]
    assert "—" in sp_line
