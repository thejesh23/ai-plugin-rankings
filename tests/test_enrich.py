import hashlib
from pathlib import Path
from unittest.mock import MagicMock

from scripts.anthropic_client import EnrichmentParseError, EnrichmentResult
from scripts.enrich import enrich_registry
from scripts.metadata import load_metadata
from scripts.models import MetadataEntry


def _readme_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_enriches_new_plugin(tmp_path: Path) -> None:
    plugins_yaml = tmp_path / "plugins.yaml"
    plugins_yaml.write_text("""
plugins:
  - id: new-plugin
    repo: o/new-plugin
    assistants: [cursor]
    added: "2026-05-28"
""")
    metadata_path = tmp_path / "metadata.json"

    gh = MagicMock()
    gh.fetch_readme.return_value = "Hello README"

    enricher = MagicMock()
    enricher.enrich.return_value = EnrichmentResult(
        description="A new plugin", category="other", tags=["workflow"])

    enrich_registry(plugins_yaml, metadata_path, gh, enricher, now="2026-05-25T00:00:00Z")

    saved = load_metadata(metadata_path)
    assert saved["new-plugin"].description == "A new plugin"
    assert saved["new-plugin"].readme_sha == _readme_sha("Hello README")
    enricher.enrich.assert_called_once()


def test_skips_when_readme_unchanged(tmp_path: Path) -> None:
    plugins_yaml = tmp_path / "plugins.yaml"
    plugins_yaml.write_text("""
plugins:
  - id: cached
    repo: o/cached
    assistants: [cursor]
    added: "2026-05-28"
""")
    metadata_path = tmp_path / "metadata.json"
    existing = MetadataEntry(
        description="cached desc", tags=["workflow"], category="other",
        enriched_at="2026-05-18T00:00:00Z", readme_sha=_readme_sha("readme v1"))
    from scripts.metadata import save_metadata
    save_metadata(metadata_path, {"cached": existing})

    gh = MagicMock()
    gh.fetch_readme.return_value = "readme v1"
    enricher = MagicMock()

    enrich_registry(plugins_yaml, metadata_path, gh, enricher, now="2026-05-25T00:00:00Z")

    enricher.enrich.assert_not_called()
    saved = load_metadata(metadata_path)
    assert saved["cached"].description == "cached desc"


def test_keeps_previous_on_llm_parse_error(tmp_path: Path) -> None:
    plugins_yaml = tmp_path / "plugins.yaml"
    plugins_yaml.write_text("""
plugins:
  - id: fragile
    repo: o/fragile
    assistants: [cursor]
    added: "2026-05-28"
""")
    metadata_path = tmp_path / "metadata.json"
    existing = MetadataEntry(
        description="old desc", tags=["workflow"], category="productivity",
        enriched_at="2026-05-01T00:00:00Z", readme_sha="oldsha")
    from scripts.metadata import save_metadata
    save_metadata(metadata_path, {"fragile": existing})

    gh = MagicMock()
    gh.fetch_readme.return_value = "new readme contents"
    enricher = MagicMock()
    enricher.enrich.side_effect = EnrichmentParseError("bad json")

    enrich_registry(plugins_yaml, metadata_path, gh, enricher, now="2026-05-25T00:00:00Z")

    saved = load_metadata(metadata_path)
    assert saved["fragile"].description == "old desc"
