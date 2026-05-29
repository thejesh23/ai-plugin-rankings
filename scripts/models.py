"""Pydantic schemas for every persisted artifact.

Every YAML/JSON file we read or write passes through one of these models so
that malformed inputs fail loudly at the I/O boundary instead of producing
silently-wrong output downstream.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from scripts.constants import ASSISTANTS, TAGS

_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

Status = Literal["ok", "missing", "archived"]
Category = Literal[
    "productivity", "testing", "debugging", "code-review",
    "documentation", "language-support", "mcp-bridge", "other",
]


class PluginEntry(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    repo: str
    assistants: list[str] = Field(min_length=1)
    added: str  # YYYY-MM-DD; not parsed to a date to keep YAML round-trip stable

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, v: str) -> str:
        if not _REPO_RE.match(v):
            raise ValueError("repo must be 'owner/name' with allowed chars [A-Za-z0-9._-]")
        return v

    @field_validator("assistants")
    @classmethod
    def _check_assistants(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ASSISTANTS
        if unknown:
            raise ValueError(f"unknown assistants: {sorted(unknown)}")
        return v


class PluginRegistry(BaseModel):
    plugins: list[PluginEntry]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> PluginRegistry:
        ids = [p.id for p in self.plugins]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate plugin ids: {dupes}")
        return self


class MetadataEntry(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    tags: list[str]
    category: Category
    enriched_at: str
    readme_sha: str

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(TAGS)
        if unknown:
            raise ValueError(f"unknown tags: {sorted(unknown)}")
        return v


class SnapshotRow(BaseModel):
    """One line in snapshots/YYYY-MM-DD.jsonl on the data branch."""
    id: str
    repo: str
    stars: int = Field(ge=0)
    forks: int = Field(ge=0)
    open_issues: int = Field(ge=0)
    archived: bool
    pushed_at: str  # ISO 8601


class LatestPlugin(BaseModel):
    id: str
    repo: str
    assistants: list[str]
    stars: int
    stars_24h: int | None
    stars_7d: int | None
    previous_stars: int | None
    archived: bool
    status: Status
    url: str
    description: str = ""  # GitHub's repo description; rendered as fallback when metadata absent


class LatestJson(BaseModel):
    generated_at: str
    plugins: list[LatestPlugin]
