"""Weekly enrichment job. For each plugin:
- Fetch README from GitHub
- If its sha256 matches metadata.json's stored value, skip (no LLM call)
- Else call the LLM, validate, update metadata
- On LLM error: keep the previous entry (don't corrupt the file)"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Protocol, cast

from scripts.anthropic_client import AnthropicEnricher, EnrichmentParseError, EnrichmentResult
from scripts.github_api import GitHubClient
from scripts.metadata import load_metadata, save_metadata
from scripts.models import Category, MetadataEntry
from scripts.plugins_yaml import load_registry

log = logging.getLogger(__name__)


class _GH(Protocol):
    def fetch_readme(self, repo: str) -> str | None: ...


class _Enricher(Protocol):
    def enrich(self, plugin_id: str, readme: str) -> EnrichmentResult: ...


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def enrich_registry(
    plugins_yaml: Path,
    metadata_path: Path,
    gh: GitHubClient | _GH,
    enricher: AnthropicEnricher | _Enricher,
    now: str,
) -> None:
    registry = load_registry(plugins_yaml)
    metadata = load_metadata(metadata_path)

    for plugin in registry.plugins:
        readme = gh.fetch_readme(plugin.repo)
        if readme is None:
            log.warning("no README for %s; skipping", plugin.id)
            continue
        sha = _sha(readme)
        existing = metadata.get(plugin.id)
        if existing is not None and existing.readme_sha == sha:
            continue
        try:
            result = enricher.enrich(plugin.id, readme)
        except EnrichmentParseError:
            log.exception("enrichment failed for %s; keeping previous", plugin.id)
            continue
        metadata[plugin.id] = MetadataEntry(
            description=result.description,
            category=cast("Category", result.category),
            tags=result.tags,
            enriched_at=now,
            readme_sha=sha,
        )

    save_metadata(metadata_path, metadata)
