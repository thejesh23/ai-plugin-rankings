import json
from unittest.mock import MagicMock

import pytest

from scripts.anthropic_client import AnthropicEnricher, EnrichmentParseError, EnrichmentResult


def _stub_client(text: str) -> MagicMock:
    """Stub an anthropic.Anthropic instance that returns a single text block."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    client.messages.create.return_value = msg
    return client


def test_enrich_valid_response() -> None:
    client = _stub_client(json.dumps({
        "description": "A workflow framework",
        "category": "productivity",
        "tags": ["workflow", "skills"],
    }))
    enricher = AnthropicEnricher(api_key="k", client=client)
    result = enricher.enrich("superpowers", "Some README text")
    assert result == EnrichmentResult(
        description="A workflow framework",
        category="productivity",
        tags=["workflow", "skills"],
    )


def test_enrich_strips_markdown_codefence() -> None:
    """LLMs sometimes wrap JSON in ```json ... ``` despite the prompt."""
    fenced = "```json\n" + json.dumps({
        "description": "x", "category": "other", "tags": ["workflow"],
    }) + "\n```"
    client = _stub_client(fenced)
    enricher = AnthropicEnricher(api_key="k", client=client)
    result = enricher.enrich("x", "readme")
    assert result.description == "x"


def test_enrich_bad_json_raises() -> None:
    client = _stub_client("not json at all")
    enricher = AnthropicEnricher(api_key="k", client=client)
    with pytest.raises(EnrichmentParseError):
        enricher.enrich("x", "readme")


def test_enrich_invalid_category_raises() -> None:
    client = _stub_client(json.dumps({
        "description": "x", "category": "made-up", "tags": ["workflow"],
    }))
    enricher = AnthropicEnricher(api_key="k", client=client)
    with pytest.raises(EnrichmentParseError):
        enricher.enrich("x", "readme")
