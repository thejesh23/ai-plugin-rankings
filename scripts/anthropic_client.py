"""Anthropic API wrapper for plugin enrichment.

The prompt instructs the model to return strict JSON from a controlled
vocabulary. We validate the JSON shape before returning; on any failure
the caller keeps the existing metadata entry instead of corrupting it."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator

from scripts.constants import CATEGORIES, TAGS


class EnrichmentParseError(Exception):
    """Raised when the LLM response cannot be parsed into a valid EnrichmentResult."""


@dataclass(frozen=True)
class EnrichmentResult:
    description: str
    category: str
    tags: list[str]


class _LLMResponse(BaseModel):
    description: str
    category: str
    tags: list[str]

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"category not in CATEGORIES: {v}")
        return v

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(TAGS)
        if unknown:
            raise ValueError(f"unknown tags: {sorted(unknown)}")
        return v


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1) if m else text


PROMPT_TEMPLATE = """You will classify a GitHub repo based on its README.

Return ONLY a JSON object with these exact keys (no prose, no markdown fences):
- description: one short sentence (<160 chars) describing what the plugin does
- category: exactly one of: {categories}
- tags: 1-5 strings, each chosen from: {tags}

README for {repo_id}:

{readme}
"""


class AnthropicEnricher:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-7",
        client: Anthropic | Any | None = None,
    ) -> None:
        self._client: Anthropic | Any = (
            client if client is not None else Anthropic(api_key=api_key)
        )
        self._model = model

    def enrich(self, plugin_id: str, readme: str) -> EnrichmentResult:
        prompt = PROMPT_TEMPLATE.format(
            categories=", ".join(CATEGORIES),
            tags=", ".join(TAGS),
            repo_id=plugin_id,
            readme=readme[:12_000],
        )
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text: str = msg.content[0].text  # type: ignore[union-attr]
        try:
            payload = json.loads(_strip_fence(text))
            parsed = _LLMResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as e:
            raise EnrichmentParseError(f"bad response for {plugin_id}: {e}") from e
        return EnrichmentResult(
            description=parsed.description,
            category=parsed.category,
            tags=parsed.tags,
        )
