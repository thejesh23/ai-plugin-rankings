# AI Plugin Rankings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a git repo that publishes daily-updated star rankings (all-time and 24h trending) of plugins for Claude Code, Cursor, GitHub Copilot, and Codex CLI, driven by three GitHub Actions workflows against a curated `plugins.yaml`.

**Architecture:** Python 3.12 scraper + renderer on the `main` branch; append-only daily snapshots on an orphan `data` branch. Three cron workflows: daily scrape/render, weekly LLM enrichment, weekly candidate discovery (PR-only, never auto-merged). All HTTP behind retry/backoff; all I/O validated by pydantic models; rendering is deterministic for golden-file testing.

**Tech Stack:** Python 3.12, `httpx`, `pydantic` v2, `PyYAML`, `anthropic` SDK, `pytest` + `respx` (HTTP mocking), `ruff`, `mypy --strict`, GitHub Actions.

**Repo root:** `/Users/thejesh/Git/ai-plugin-rankings` (already `git init`'d on `main`; the design spec is the only existing commit).

**Spec reference:** `docs/superpowers/specs/2026-05-28-ai-plugin-rankings-design.md`

---

## Task 1: Project skeleton (pyproject.toml, .gitignore, dirs)

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `scripts/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/fixtures/.gitkeep` (empty)
- Create: `tests/golden/.gitkeep` (empty)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ai-plugin-rankings"
version = "0.1.0"
description = "Daily-updated star rankings of AI coding assistant plugins"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "anthropic>=0.40",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "respx>=0.21",
    "ruff>=0.5",
    "mypy>=1.10",
    "types-PyYAML",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["scripts", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
*.tmp
.env
```

- [ ] **Step 3: Create empty package marker files**

Run:
```bash
mkdir -p scripts tests/fixtures tests/golden
touch scripts/__init__.py tests/__init__.py tests/fixtures/.gitkeep tests/golden/.gitkeep
```

- [ ] **Step 4: Install dev deps and verify tooling**

Run:
```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy scripts/ && pytest
```

Expected: ruff passes (no files to check yet beyond empty `__init__.py`), mypy passes (no errors), pytest exits with "no tests ran" (exit code 5 is OK; treat any other non-zero as failure).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore scripts/__init__.py tests/__init__.py tests/fixtures/.gitkeep tests/golden/.gitkeep
git commit -m "Project skeleton: pyproject, gitignore, package layout"
```

---

## Task 2: Constants (category enum, tag vocabulary)

**Files:**
- Create: `scripts/constants.py`
- Create: `tests/test_constants.py`

- [ ] **Step 1: Write the failing test**

`tests/test_constants.py`:

```python
from scripts.constants import CATEGORIES, TAGS, ASSISTANTS


def test_categories_are_unique_strings():
    assert len(CATEGORIES) == len(set(CATEGORIES))
    assert all(isinstance(c, str) for c in CATEGORIES)
    assert "productivity" in CATEGORIES
    assert "other" in CATEGORIES  # fallback bucket must exist


def test_tags_are_unique_strings():
    assert len(TAGS) == len(set(TAGS))
    assert all(isinstance(t, str) for t in TAGS)


def test_assistants_set():
    assert ASSISTANTS == {"claude-code", "cursor", "copilot", "codex"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_constants.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.constants'`

- [ ] **Step 3: Implement `scripts/constants.py`**

```python
"""Controlled vocabularies. The LLM enrichment prompt selects from these lists;
it never invents new categories or tags."""

CATEGORIES: tuple[str, ...] = (
    "productivity",
    "testing",
    "debugging",
    "code-review",
    "documentation",
    "language-support",
    "mcp-bridge",
    "other",
)

TAGS: tuple[str, ...] = (
    "workflow", "skills", "tdd", "agents", "automation",
    "lint", "format", "refactor", "git", "github",
    "browser", "headless", "screenshot", "design", "ui",
    "shell", "cli", "python", "typescript", "rust",
    "go", "java", "data", "sql", "search",
    "embeddings", "rag", "memory", "context", "logging",
)

ASSISTANTS: frozenset[str] = frozenset({"claude-code", "cursor", "copilot", "codex"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_constants.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/constants.py tests/test_constants.py
git commit -m "Add category/tag/assistant controlled vocabularies"
```

---

## Task 3: Pydantic models

**Files:**
- Create: `scripts/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from scripts.models import (
    PluginEntry, PluginRegistry, MetadataEntry,
    SnapshotRow, LatestPlugin, LatestJson,
)


def test_plugin_entry_valid():
    p = PluginEntry(
        id="superpowers", repo="obra/superpowers",
        assistants=["claude-code"], added="2026-05-28",
    )
    assert p.id == "superpowers"
    assert p.assistants == ["claude-code"]


def test_plugin_entry_rejects_unknown_assistant():
    with pytest.raises(ValidationError):
        PluginEntry(
            id="x", repo="o/x", assistants=["windsurf"], added="2026-05-28",
        )


def test_plugin_entry_rejects_bad_repo_format():
    with pytest.raises(ValidationError):
        PluginEntry(
            id="x", repo="not-a-slash-pair", assistants=["cursor"], added="2026-05-28",
        )


def test_plugin_registry_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        PluginRegistry(plugins=[
            PluginEntry(id="a", repo="o/a", assistants=["cursor"], added="2026-05-28"),
            PluginEntry(id="a", repo="o/b", assistants=["cursor"], added="2026-05-28"),
        ])


def test_metadata_entry_rejects_unknown_category():
    with pytest.raises(ValidationError):
        MetadataEntry(
            description="x", tags=["workflow"], category="not-a-category",
            enriched_at="2026-05-25T00:00:00Z", readme_sha="abc",
        )


def test_snapshot_row_roundtrip():
    row = SnapshotRow(
        id="x", repo="o/x", stars=100, forks=10,
        open_issues=5, archived=False, pushed_at="2026-05-27T00:00:00Z",
    )
    assert row.model_dump()["stars"] == 100


def test_latest_plugin_status_enum():
    with pytest.raises(ValidationError):
        LatestPlugin(
            id="x", repo="o/x", assistants=["cursor"], stars=1,
            stars_24h=0, stars_7d=0, previous_stars=1, archived=False,
            status="weird", url="https://github.com/o/x",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `scripts.models` does not exist yet.

- [ ] **Step 3: Implement `scripts/models.py`**

```python
"""Pydantic schemas for every persisted artifact.

Every YAML/JSON file we read or write passes through one of these models so
that malformed inputs fail loudly at the I/O boundary instead of producing
silently-wrong output downstream.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from scripts.constants import ASSISTANTS, CATEGORIES, TAGS

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
    def _check_unique_ids(self) -> "PluginRegistry":
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


class LatestJson(BaseModel):
    generated_at: str
    plugins: list[LatestPlugin]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v && mypy scripts/ tests/`
Expected: 7 passed, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/models.py tests/test_models.py
git commit -m "Add pydantic models for every persisted artifact"
```

---

## Task 4: plugins.yaml loader

**Files:**
- Create: `scripts/plugins_yaml.py`
- Create: `tests/test_plugins_yaml.py`
- Create: `tests/fixtures/plugins-good.yaml`
- Create: `tests/fixtures/plugins-bad-duplicate.yaml`

- [ ] **Step 1: Create fixture files**

`tests/fixtures/plugins-good.yaml`:

```yaml
plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
  - id: example-cursor
    repo: someone/example-cursor
    assistants: [cursor]
    added: "2026-05-28"
```

`tests/fixtures/plugins-bad-duplicate.yaml`:

```yaml
plugins:
  - id: dup
    repo: o/a
    assistants: [cursor]
    added: "2026-05-28"
  - id: dup
    repo: o/b
    assistants: [cursor]
    added: "2026-05-28"
```

- [ ] **Step 2: Write the failing test**

`tests/test_plugins_yaml.py`:

```python
from pathlib import Path

import pytest

from scripts.plugins_yaml import load_registry

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_good_registry():
    reg = load_registry(FIXTURES / "plugins-good.yaml")
    assert len(reg.plugins) == 2
    assert reg.plugins[0].id == "superpowers"


def test_load_duplicate_ids_raises():
    with pytest.raises(ValueError, match="duplicate plugin ids"):
        load_registry(FIXTURES / "plugins-bad-duplicate.yaml")


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "nope.yaml")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_plugins_yaml.py -v`
Expected: FAIL — `scripts.plugins_yaml` missing.

- [ ] **Step 4: Implement `scripts/plugins_yaml.py`**

```python
from pathlib import Path

import yaml

from scripts.models import PluginRegistry


def load_registry(path: Path) -> PluginRegistry:
    """Load and validate plugins.yaml. Raises FileNotFoundError on missing
    file, ValidationError on schema violations."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return PluginRegistry.model_validate(raw)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_plugins_yaml.py -v && mypy scripts/`
Expected: 3 passed, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/plugins_yaml.py tests/test_plugins_yaml.py tests/fixtures/plugins-good.yaml tests/fixtures/plugins-bad-duplicate.yaml
git commit -m "Load and validate plugins.yaml"
```

---

## Task 5: Snapshot read/write (JSONL)

**Files:**
- Create: `scripts/snapshot.py`
- Create: `tests/test_snapshot.py`

- [ ] **Step 1: Write the failing test**

`tests/test_snapshot.py`:

```python
from pathlib import Path

import pytest

from scripts.models import SnapshotRow
from scripts.snapshot import write_snapshot, read_snapshot, snapshot_path


SAMPLE = [
    SnapshotRow(id="a", repo="o/a", stars=10, forks=1, open_issues=0,
                archived=False, pushed_at="2026-05-27T00:00:00Z"),
    SnapshotRow(id="b", repo="o/b", stars=20, forks=2, open_issues=3,
                archived=True, pushed_at="2026-05-26T00:00:00Z"),
]


def test_snapshot_path():
    base = Path("/tmp/data")
    assert snapshot_path(base, "2026-05-28") == base / "snapshots" / "2026-05-28.jsonl"


def test_write_and_read_roundtrip(tmp_path: Path):
    p = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    assert p.exists()
    loaded = read_snapshot(p)
    assert loaded == SAMPLE


def test_write_is_deterministic(tmp_path: Path):
    """Writing the same data twice produces byte-identical files."""
    p1 = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    bytes1 = p1.read_bytes()
    p2 = write_snapshot(tmp_path, "2026-05-28", SAMPLE)
    bytes2 = p2.read_bytes()
    assert bytes1 == bytes2


def test_read_missing_returns_none(tmp_path: Path):
    """Missing snapshot is not an error — it just means no history yet."""
    missing = tmp_path / "snapshots" / "1900-01-01.jsonl"
    with pytest.raises(FileNotFoundError):
        read_snapshot(missing)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_snapshot.py -v`
Expected: FAIL — `scripts.snapshot` missing.

- [ ] **Step 3: Implement `scripts/snapshot.py`**

```python
"""Snapshot files live on the orphan `data` branch.
One file per day, one line per plugin (JSONL). Idempotent overwrite."""
import json
from pathlib import Path
from typing import Iterable

from scripts.models import SnapshotRow


def snapshot_path(data_dir: Path, date: str) -> Path:
    return data_dir / "snapshots" / f"{date}.jsonl"


def write_snapshot(data_dir: Path, date: str, rows: Iterable[SnapshotRow]) -> Path:
    """Write a snapshot atomically. Idempotent: same input → same bytes."""
    rows_sorted = sorted(rows, key=lambda r: r.id)
    path = snapshot_path(data_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows_sorted:
            # sort_keys=True ensures byte-determinism across Python runs.
            f.write(json.dumps(row.model_dump(), sort_keys=True, separators=(",", ":")))
            f.write("\n")
    tmp.replace(path)
    return path


def read_snapshot(path: Path) -> list[SnapshotRow]:
    """Read a snapshot. Raises FileNotFoundError if absent."""
    with path.open("r", encoding="utf-8") as f:
        return [SnapshotRow.model_validate_json(line) for line in f if line.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_snapshot.py -v && mypy scripts/`
Expected: 4 passed, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/snapshot.py tests/test_snapshot.py
git commit -m "Snapshot read/write with deterministic JSONL output"
```

---

## Task 6: metadata.json read/write

**Files:**
- Create: `scripts/metadata.py`
- Create: `tests/test_metadata.py`

- [ ] **Step 1: Write the failing test**

`tests/test_metadata.py`:

```python
from pathlib import Path

from scripts.metadata import load_metadata, save_metadata
from scripts.models import MetadataEntry


ENTRY = MetadataEntry(
    description="A tool",
    tags=["workflow", "skills"],
    category="productivity",
    enriched_at="2026-05-25T00:00:00Z",
    readme_sha="abc123",
)


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "metadata.json"
    save_metadata(path, {"superpowers": ENTRY})
    loaded = load_metadata(path)
    assert loaded == {"superpowers": ENTRY}


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_metadata(tmp_path / "absent.json") == {}


def test_save_is_deterministic(tmp_path: Path):
    path = tmp_path / "metadata.json"
    save_metadata(path, {"b": ENTRY, "a": ENTRY})
    b1 = path.read_bytes()
    save_metadata(path, {"a": ENTRY, "b": ENTRY})
    b2 = path.read_bytes()
    assert b1 == b2  # keys sorted on save
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metadata.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/metadata.py`**

```python
"""metadata.json holds LLM-generated descriptions/tags per plugin.
Refreshed weekly; daily job reads it but does not modify."""
import json
from pathlib import Path

from scripts.models import MetadataEntry


def load_metadata(path: Path) -> dict[str, MetadataEntry]:
    """Returns {} if the file doesn't exist (first run)."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: MetadataEntry.model_validate(v) for k, v in raw.items()}


def save_metadata(path: Path, data: dict[str, MetadataEntry]) -> None:
    """Save with sorted keys and consistent indentation so git diffs are clean."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {k: data[k].model_dump() for k in sorted(data.keys())}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_metadata.py -v && mypy scripts/`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/metadata.py tests/test_metadata.py
git commit -m "metadata.json read/write with sorted-key determinism"
```

---

## Task 7: GitHub API client

**Files:**
- Create: `scripts/github_api.py`
- Create: `tests/test_github_api.py`

- [ ] **Step 1: Write the failing test**

`tests/test_github_api.py`:

```python
import httpx
import pytest
import respx

from scripts.github_api import GitHubClient, RepoData, RateLimitError, RepoMissingError


@respx.mock
def test_fetch_repo_success():
    respx.get("https://api.github.com/repos/obra/superpowers").mock(
        return_value=httpx.Response(200, json={
            "full_name": "obra/superpowers",
            "stargazers_count": 1247,
            "forks_count": 89,
            "open_issues_count": 12,
            "archived": False,
            "pushed_at": "2026-05-27T18:22:00Z",
        })
    )
    client = GitHubClient(token="t")
    data = client.fetch_repo("obra/superpowers")
    assert data == RepoData(
        repo="obra/superpowers", stars=1247, forks=89,
        open_issues=12, archived=False, pushed_at="2026-05-27T18:22:00Z",
    )


@respx.mock
def test_fetch_repo_404_raises_missing():
    respx.get("https://api.github.com/repos/o/gone").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    client = GitHubClient(token="t")
    with pytest.raises(RepoMissingError):
        client.fetch_repo("o/gone")


@respx.mock
def test_fetch_repo_rate_limit_raises_after_retry():
    respx.get("https://api.github.com/repos/o/x").mock(
        return_value=httpx.Response(403, json={"message": "rate limit"})
    )
    client = GitHubClient(token="t", max_retries=1, retry_base=0.01)
    with pytest.raises(RateLimitError):
        client.fetch_repo("o/x")


@respx.mock
def test_fetch_repo_500_retries_then_succeeds():
    route = respx.get("https://api.github.com/repos/o/x")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json={
            "full_name": "o/x", "stargazers_count": 5, "forks_count": 0,
            "open_issues_count": 0, "archived": False,
            "pushed_at": "2026-05-27T00:00:00Z",
        }),
    ]
    client = GitHubClient(token="t", max_retries=3, retry_base=0.01)
    data = client.fetch_repo("o/x")
    assert data.stars == 5


@respx.mock
def test_fetch_readme_returns_text():
    respx.get("https://api.github.com/repos/o/x/readme").mock(
        return_value=httpx.Response(200, json={
            "encoding": "base64",
            # base64 of "Hello README"
            "content": "SGVsbG8gUkVBRE1F",
        })
    )
    client = GitHubClient(token="t")
    assert client.fetch_readme("o/x") == "Hello README"


@respx.mock
def test_fetch_readme_404_returns_none():
    respx.get("https://api.github.com/repos/o/x/readme").mock(
        return_value=httpx.Response(404)
    )
    client = GitHubClient(token="t")
    assert client.fetch_readme("o/x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_github_api.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/github_api.py`**

```python
"""Thin GitHub REST wrapper with retry/backoff."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx


class RateLimitError(Exception):
    """Raised when GitHub returns 403 after retries."""


class RepoMissingError(Exception):
    """Raised when a repo returns 404."""


@dataclass(frozen=True)
class RepoData:
    repo: str
    stars: int
    forks: int
    open_issues: int
    archived: bool
    pushed_at: str


class GitHubClient:
    """Synchronous client. One call per repo; no batching required for current scale."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        retry_base: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )
        self._max_retries = max_retries
        self._retry_base = retry_base

    def fetch_repo(self, repo: str) -> RepoData:
        resp = self._request_with_retry(f"/repos/{repo}")
        if resp.status_code == 404:
            raise RepoMissingError(repo)
        resp.raise_for_status()
        body = resp.json()
        return RepoData(
            repo=body["full_name"],
            stars=body["stargazers_count"],
            forks=body["forks_count"],
            open_issues=body["open_issues_count"],
            archived=body["archived"],
            pushed_at=body["pushed_at"],
        )

    def fetch_readme(self, repo: str) -> str | None:
        """Returns README text, or None if the repo has no README."""
        resp = self._request_with_retry(f"/repos/{repo}/readme")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        if body.get("encoding") != "base64":
            raise RuntimeError(f"unexpected readme encoding: {body.get('encoding')}")
        return base64.b64decode(body["content"]).decode("utf-8", errors="replace")

    def _request_with_retry(self, path: str) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            resp = self._client.get(path)
            if resp.status_code < 500 and resp.status_code != 403:
                return resp
            last = resp
            if attempt < self._max_retries:
                time.sleep(self._retry_base * (2 ** attempt))
        assert last is not None
        if last.status_code == 403:
            raise RateLimitError(path)
        last.raise_for_status()
        return last  # unreachable

    def close(self) -> None:
        self._client.close()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_github_api.py -v && mypy scripts/`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/github_api.py tests/test_github_api.py
git commit -m "GitHub API client with retry/backoff"
```

---

## Task 8: Delta computation

**Files:**
- Create: `scripts/delta.py`
- Create: `tests/test_delta.py`

- [ ] **Step 1: Write the failing test**

`tests/test_delta.py`:

```python
from scripts.delta import compute_delta
from scripts.models import SnapshotRow


def row(id: str, stars: int) -> SnapshotRow:
    return SnapshotRow(id=id, repo=f"o/{id}", stars=stars, forks=0,
                       open_issues=0, archived=False, pushed_at="2026-05-27T00:00:00Z")


def test_delta_basic():
    today = [row("a", 100), row("b", 50)]
    yesterday = [row("a", 90), row("b", 50)]
    assert compute_delta(today, yesterday) == {"a": 10, "b": 0}


def test_delta_new_plugin_returns_none():
    """A plugin not in 'previous' has no delta — neither 0 nor stars."""
    today = [row("new", 25)]
    yesterday: list[SnapshotRow] = []
    assert compute_delta(today, yesterday) == {"new": None}


def test_delta_missing_previous_means_none_for_all():
    today = [row("a", 100)]
    assert compute_delta(today, None) == {"a": None}


def test_delta_handles_unstarred_decline():
    """Stars can go down (unstar). Delta can be negative."""
    today = [row("a", 50)]
    yesterday = [row("a", 80)]
    assert compute_delta(today, yesterday) == {"a": -30}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delta.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/delta.py`**

```python
"""Compute star deltas between two snapshots.

A None delta means we have no data for that comparison window (e.g. brand-new
plugin, or no snapshot from N days ago). The renderer displays None as "—",
distinguished from 0 (no change)."""
from typing import Iterable

from scripts.models import SnapshotRow


def compute_delta(
    today: Iterable[SnapshotRow],
    previous: Iterable[SnapshotRow] | None,
) -> dict[str, int | None]:
    """Returns {plugin_id: stars_delta_or_None}."""
    if previous is None:
        return {r.id: None for r in today}
    prev_by_id = {r.id: r for r in previous}
    out: dict[str, int | None] = {}
    for r in today:
        prev = prev_by_id.get(r.id)
        out[r.id] = (r.stars - prev.stars) if prev is not None else None
    return out
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_delta.py -v && mypy scripts/`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/delta.py tests/test_delta.py
git commit -m "Star delta computation with None for missing previous"
```

---

## Task 9: Ranking sort

**Files:**
- Create: `scripts/rank.py`
- Create: `tests/test_rank.py`

- [ ] **Step 1: Write the failing test**

`tests/test_rank.py`:

```python
from scripts.models import LatestPlugin
from scripts.rank import rank_by_stars, rank_by_trending


def plug(
    id: str, stars: int, stars_24h: int | None = 0,
    archived: bool = False, status: str = "ok",
) -> LatestPlugin:
    return LatestPlugin(
        id=id, repo=f"o/{id}", assistants=["claude-code"],
        stars=stars, stars_24h=stars_24h, stars_7d=None,
        previous_stars=stars - (stars_24h or 0), archived=archived,
        status=status, url=f"https://github.com/o/{id}",
    )


def test_rank_by_stars_descending():
    plugins = [plug("a", 100), plug("b", 50), plug("c", 200)]
    ranked = rank_by_stars(plugins)
    assert [p.id for p in ranked] == ["c", "a", "b"]


def test_rank_archived_sorts_to_bottom():
    plugins = [
        plug("a", 100), plug("z-archived", 500, archived=True), plug("b", 50),
    ]
    ranked = rank_by_stars(plugins)
    assert [p.id for p in ranked] == ["a", "b", "z-archived"]


def test_rank_by_trending_descending_by_24h():
    plugins = [plug("a", 100, stars_24h=5), plug("b", 50, stars_24h=20),
               plug("c", 200, stars_24h=1)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["b", "a", "c"]


def test_rank_by_trending_none_delta_sorts_to_bottom():
    """Plugins with no delta (new, no history) rank below those with 0."""
    plugins = [plug("a", 100, stars_24h=None), plug("b", 50, stars_24h=0)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["b", "a"]


def test_rank_by_trending_ties_broken_by_total_stars():
    plugins = [plug("low", 50, stars_24h=10), plug("high", 500, stars_24h=10)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["high", "low"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rank.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/rank.py`**

```python
"""Sort plugins for the two ranking views.

Both rankings push archived plugins to the bottom — they're tracked for
historical interest but shouldn't dominate the visible top of any list."""
from scripts.models import LatestPlugin


def rank_by_stars(plugins: list[LatestPlugin]) -> list[LatestPlugin]:
    return sorted(
        plugins,
        # Archived first (True > False), then descending stars.
        key=lambda p: (p.archived, -p.stars, p.id),
    )


def rank_by_trending(plugins: list[LatestPlugin]) -> list[LatestPlugin]:
    return sorted(
        plugins,
        # Archived bottom; None delta below 0-delta; then descending delta;
        # tie-break by total stars desc; finally by id for stability.
        key=lambda p: (
            p.archived,
            p.stars_24h is None,
            -(p.stars_24h or 0),
            -p.stars,
            p.id,
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_rank.py -v && mypy scripts/`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/rank.py tests/test_rank.py
git commit -m "Ranking sorts with archived-bottom and stable tie-breaking"
```

---

## Task 10: Markdown rendering

**Files:**
- Create: `scripts/render.py`
- Create: `tests/test_render.py`
- Create: `tests/fixtures/latest-3plugins.json`
- Create: `tests/golden/README.md`
- Create: `tests/golden/all.md`
- Create: `tests/golden/trending.md`
- Create: `tests/golden/claude-code.md`

- [ ] **Step 1: Create the fixture file**

`tests/fixtures/latest-3plugins.json`:

```json
{
  "generated_at": "2026-05-28T03:00:00Z",
  "plugins": [
    {
      "id": "superpowers", "repo": "obra/superpowers",
      "assistants": ["claude-code"], "stars": 1247, "stars_24h": 18,
      "stars_7d": 92, "previous_stars": 1229, "archived": false,
      "status": "ok", "url": "https://github.com/obra/superpowers"
    },
    {
      "id": "cursor-tool", "repo": "someone/cursor-tool",
      "assistants": ["cursor"], "stars": 800, "stars_24h": 5,
      "stars_7d": 40, "previous_stars": 795, "archived": false,
      "status": "ok", "url": "https://github.com/someone/cursor-tool"
    },
    {
      "id": "multi-target", "repo": "org/multi",
      "assistants": ["cursor", "claude-code"], "stars": 300, "stars_24h": 50,
      "stars_7d": 200, "previous_stars": 250, "archived": false,
      "status": "ok", "url": "https://github.com/org/multi"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_render.py`:

```python
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


def test_render_matches_golden():
    output = render_all(_load_latest(), _metadata())
    assert output.readme == (GOLDEN / "README.md").read_text()
    assert output.rankings["all"] == (GOLDEN / "all.md").read_text()
    assert output.rankings["trending"] == (GOLDEN / "trending.md").read_text()
    assert output.rankings["claude-code"] == (GOLDEN / "claude-code.md").read_text()


def test_render_is_deterministic():
    out1 = render_all(_load_latest(), _metadata())
    out2 = render_all(_load_latest(), _metadata())
    assert out1.readme == out2.readme
    assert out1.rankings == out2.rankings


def test_multi_target_appears_in_each_assistant_file():
    output = render_all(_load_latest(), _metadata())
    assert "multi-target" in output.rankings["claude-code"]
    assert "multi-target" in output.rankings["cursor"]


def test_missing_metadata_renders_with_em_dash():
    """A plugin in latest.json but absent from metadata renders with '—'."""
    output = render_all(_load_latest(), {})
    # superpowers has no metadata → description column should show em-dash.
    sp_line = [l for l in output.rankings["all"].splitlines() if "superpowers" in l][0]
    assert "—" in sp_line
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_render.py -v`
Expected: FAIL — `scripts.render` missing.

- [ ] **Step 4: Implement `scripts/render.py`**

```python
"""Render latest.json + metadata into markdown files.

Deterministic: same input → same bytes. No timestamps in per-ranking files;
the README does carry generated_at since freshness is a user-facing signal."""
from __future__ import annotations

from dataclasses import dataclass

from scripts.models import LatestJson, LatestPlugin, MetadataEntry
from scripts.rank import rank_by_stars, rank_by_trending

ASSISTANT_LABELS: dict[str, str] = {
    "claude-code": "Claude Code",
    "cursor": "Cursor",
    "copilot": "GitHub Copilot",
    "codex": "Codex CLI",
}

TOP_N = 20
DASH = "—"


@dataclass(frozen=True)
class RenderOutput:
    readme: str
    rankings: dict[str, str]  # keys: "all", "trending", plus each assistant id


def _row(p: LatestPlugin, rank: int, meta: dict[str, MetadataEntry]) -> str:
    md = meta.get(p.id)
    desc = md.description if md else DASH
    cat = md.category if md else DASH
    assistants = ", ".join(ASSISTANT_LABELS[a] for a in p.assistants)
    stars = f"{p.stars:,}"
    d24 = DASH if p.stars_24h is None else f"{p.stars_24h:+,}"
    d7 = DASH if p.stars_7d is None else f"{p.stars_7d:+,}"
    name = f"[{p.id}]({p.url})"
    if p.archived:
        name = f"~~{name}~~"
    return f"| {rank} | {name} | {desc} | {assistants} | {stars} | {d24} | {d7} | {cat} |"


def _table(plugins: list[LatestPlugin], meta: dict[str, MetadataEntry]) -> str:
    header = "| Rank | Plugin | Description | Assistants | Stars | 24h | 7d | Category |\n"
    sep = "|---:|---|---|---|---:|---:|---:|---|\n"
    body = "\n".join(_row(p, i + 1, meta) for i, p in enumerate(plugins))
    return header + sep + body + "\n"


def _per_assistant_file(
    assistant: str, plugins: list[LatestPlugin], meta: dict[str, MetadataEntry],
) -> str:
    filtered = [p for p in plugins if assistant in p.assistants]
    trending = rank_by_trending(filtered)
    all_time = rank_by_stars(filtered)
    label = ASSISTANT_LABELS[assistant]
    parts = [
        f"# {label} plugins\n",
        f"{len(filtered)} plugin(s). Trending sort uses 24h star delta.\n",
        "## Trending (24h)\n",
        _table(trending, meta),
        "## All-time (stars)\n",
        _table(all_time, meta),
    ]
    return "\n".join(parts)


def _readme(latest: LatestJson, meta: dict[str, MetadataEntry]) -> str:
    trending = rank_by_trending(latest.plugins)[:TOP_N]
    all_time = rank_by_stars(latest.plugins)[:TOP_N]
    counts = {a: sum(1 for p in latest.plugins if a in p.assistants)
              for a in ASSISTANT_LABELS}
    by_assistant = "\n".join(
        f"- [{ASSISTANT_LABELS[a]}](rankings/{a}.md) — {counts[a]} plugins"
        for a in ASSISTANT_LABELS
    )
    return "\n".join([
        "# AI Coding Assistant Plugin Rankings\n",
        f"Updated {latest.generated_at}. Source data in `data/`, history in `data` branch.\n",
        f"## Top {TOP_N} trending (24h)\n",
        _table(trending, meta),
        f"## Top {TOP_N} all-time (stars)\n",
        _table(all_time, meta),
        "## By assistant\n",
        by_assistant + "\n",
        "## Submit a plugin\n",
        "Open a PR adding an entry to `plugins.yaml`.\n",
    ])


def render_all(latest: LatestJson, meta: dict[str, MetadataEntry]) -> RenderOutput:
    rankings = {
        "all": "# All plugins by stars\n\n" + _table(rank_by_stars(latest.plugins), meta),
        "trending": "# All plugins by 24h trending\n\n" + _table(
            rank_by_trending(latest.plugins), meta),
    }
    for a in ASSISTANT_LABELS:
        rankings[a] = _per_assistant_file(a, latest.plugins, meta)
    return RenderOutput(readme=_readme(latest, meta), rankings=rankings)
```

- [ ] **Step 5: Generate the golden files via the implementation**

The cleanest way to create golden files is to run the rendering code once and save the output, then inspect it manually for correctness. Create a one-off generation script in the tests directory.

Run from repo root:
```bash
python -c "
import json
from pathlib import Path
from scripts.models import LatestJson, MetadataEntry
from scripts.render import render_all

FIXTURES = Path('tests/fixtures')
GOLDEN = Path('tests/golden')
GOLDEN.mkdir(exist_ok=True)

latest = LatestJson.model_validate_json((FIXTURES/'latest-3plugins.json').read_text())
meta = {
    'superpowers': MetadataEntry(description='Workflow framework with skills',
        tags=['workflow','skills'], category='productivity',
        enriched_at='2026-05-25T00:00:00Z', readme_sha='x'),
    'cursor-tool': MetadataEntry(description='Cursor productivity helper',
        tags=['workflow'], category='productivity',
        enriched_at='2026-05-25T00:00:00Z', readme_sha='x'),
    'multi-target': MetadataEntry(description='Cross-assistant utility',
        tags=['automation'], category='productivity',
        enriched_at='2026-05-25T00:00:00Z', readme_sha='x'),
}
out = render_all(latest, meta)
(GOLDEN/'README.md').write_text(out.readme)
for k, v in out.rankings.items():
    (GOLDEN/f'{k}.md').write_text(v)
print('Golden files written.')
"
```

Inspect each generated file manually:
- `cat tests/golden/README.md` — top-level should have correct sections and 3 plugins
- `cat tests/golden/claude-code.md` — should contain `superpowers` and `multi-target`, not `cursor-tool`
- `cat tests/golden/cursor.md` — should contain `cursor-tool` and `multi-target`, not `superpowers`
- `cat tests/golden/all.md` — should contain all 3, ordered superpowers > cursor-tool > multi-target

If anything looks wrong, fix `render.py` and re-run the generation.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_render.py -v && mypy scripts/`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/render.py tests/test_render.py tests/fixtures/latest-3plugins.json tests/golden/
git commit -m "Markdown rendering with golden-file determinism"
```

---

## Task 11: Anthropic client wrapper

**Files:**
- Create: `scripts/anthropic_client.py`
- Create: `tests/test_anthropic_client.py`

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_client.py`:

```python
import json
from unittest.mock import MagicMock

import pytest

from scripts.anthropic_client import AnthropicEnricher, EnrichmentResult, EnrichmentParseError


def _stub_client(text: str) -> MagicMock:
    """Stub an anthropic.Anthropic instance that returns a single text block."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    client.messages.create.return_value = msg
    return client


def test_enrich_valid_response():
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


def test_enrich_strips_markdown_codefence():
    """LLMs sometimes wrap JSON in ```json ... ``` despite the prompt."""
    fenced = "```json\n" + json.dumps({
        "description": "x", "category": "other", "tags": ["workflow"],
    }) + "\n```"
    client = _stub_client(fenced)
    enricher = AnthropicEnricher(api_key="k", client=client)
    result = enricher.enrich("x", "readme")
    assert result.description == "x"


def test_enrich_bad_json_raises():
    client = _stub_client("not json at all")
    enricher = AnthropicEnricher(api_key="k", client=client)
    with pytest.raises(EnrichmentParseError):
        enricher.enrich("x", "readme")


def test_enrich_invalid_category_raises():
    client = _stub_client(json.dumps({
        "description": "x", "category": "made-up", "tags": ["workflow"],
    }))
    enricher = AnthropicEnricher(api_key="k", client=client)
    with pytest.raises(EnrichmentParseError):
        enricher.enrich("x", "readme")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_anthropic_client.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/anthropic_client.py`**

```python
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
        self._client = client if client is not None else Anthropic(api_key=api_key)
        self._model = model

    def enrich(self, plugin_id: str, readme: str) -> EnrichmentResult:
        prompt = PROMPT_TEMPLATE.format(
            categories=", ".join(CATEGORIES),
            tags=", ".join(TAGS),
            repo_id=plugin_id,
            readme=readme[:12_000],  # cap to keep tokens predictable
        )
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_anthropic_client.py -v && mypy scripts/`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/anthropic_client.py tests/test_anthropic_client.py
git commit -m "Anthropic enrichment client with strict response validation"
```

---

## Task 12: Enrichment orchestrator (weekly job)

**Files:**
- Create: `scripts/enrich.py`
- Create: `tests/test_enrich.py`

- [ ] **Step 1: Write the failing test**

`tests/test_enrich.py`:

```python
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

from scripts.anthropic_client import EnrichmentResult, EnrichmentParseError
from scripts.enrich import enrich_registry
from scripts.metadata import load_metadata
from scripts.models import MetadataEntry


def _readme_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_enriches_new_plugin(tmp_path: Path):
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


def test_skips_when_readme_unchanged(tmp_path: Path):
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


def test_keeps_previous_on_llm_parse_error(tmp_path: Path):
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
    assert saved["fragile"].description == "old desc"  # unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enrich.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/enrich.py`**

```python
"""Weekly enrichment job. For each plugin:
- Fetch README from GitHub
- If its sha256 matches metadata.json's stored value, skip (no LLM call)
- Else call the LLM, validate, update metadata
- On LLM error: keep the previous entry (don't corrupt the file)"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Protocol

from scripts.anthropic_client import AnthropicEnricher, EnrichmentParseError
from scripts.github_api import GitHubClient
from scripts.metadata import load_metadata, save_metadata
from scripts.models import MetadataEntry
from scripts.plugins_yaml import load_registry

log = logging.getLogger(__name__)


class _GH(Protocol):
    def fetch_readme(self, repo: str) -> str | None: ...


class _Enricher(Protocol):
    def enrich(self, plugin_id: str, readme: str) -> "object": ...


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
            continue  # unchanged → skip LLM call
        try:
            result = enricher.enrich(plugin.id, readme)
        except EnrichmentParseError:
            log.exception("enrichment failed for %s; keeping previous", plugin.id)
            continue
        metadata[plugin.id] = MetadataEntry(
            description=result.description,  # type: ignore[union-attr]
            category=result.category,  # type: ignore[union-attr]
            tags=result.tags,  # type: ignore[union-attr]
            enriched_at=now,
            readme_sha=sha,
        )

    save_metadata(metadata_path, metadata)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_enrich.py -v && mypy scripts/`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/enrich.py tests/test_enrich.py
git commit -m "Weekly enrichment orchestrator with sha-based skip"
```

---

## Task 13: Daily orchestrator (scrape.py)

**Files:**
- Create: `scripts/scrape.py`
- Create: `tests/test_scrape.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scrape.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from scripts.github_api import RepoData, RepoMissingError
from scripts.models import SnapshotRow
from scripts.scrape import run_daily
from scripts.snapshot import write_snapshot


def _yesterday_snapshot(data_dir: Path) -> None:
    write_snapshot(data_dir, "2026-05-27", [
        SnapshotRow(id="a", repo="o/a", stars=90, forks=1, open_issues=0,
                    archived=False, pushed_at="2026-05-26T00:00:00Z"),
    ])


def test_daily_run_writes_snapshot_and_latest(tmp_path: Path):
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: a
    repo: o/a
    assistants: [cursor]
    added: "2026-05-28"
""")
    _yesterday_snapshot(data_dir)

    gh = MagicMock()
    gh.fetch_repo.return_value = RepoData(
        repo="o/a", stars=100, forks=2, open_issues=3,
        archived=False, pushed_at="2026-05-27T18:00:00Z")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    snapshot_path = data_dir / "snapshots" / "2026-05-28.jsonl"
    assert snapshot_path.exists()
    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    assert latest["plugins"][0]["stars"] == 100
    assert latest["plugins"][0]["stars_24h"] == 10  # 100 - 90


def test_daily_run_marks_missing_plugin(tmp_path: Path):
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: ghost
    repo: o/ghost
    assistants: [cursor]
    added: "2026-05-28"
""")
    gh = MagicMock()
    gh.fetch_repo.side_effect = RepoMissingError("o/ghost")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    assert latest["plugins"][0]["status"] == "missing"


def test_daily_run_renders_readme_and_rankings(tmp_path: Path):
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    (main_dir / "plugins.yaml").write_text("""
plugins:
  - id: a
    repo: o/a
    assistants: [cursor]
    added: "2026-05-28"
""")
    gh = MagicMock()
    gh.fetch_repo.return_value = RepoData(
        repo="o/a", stars=10, forks=0, open_issues=0,
        archived=False, pushed_at="2026-05-27T00:00:00Z")

    run_daily(main_dir, data_dir, gh, today="2026-05-28")

    assert (main_dir / "README.md").exists()
    assert (main_dir / "rankings" / "cursor.md").exists()
    assert (main_dir / "rankings" / "all.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scrape.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/scrape.py`**

```python
"""Daily orchestrator. Reads plugins.yaml, hits GitHub, writes snapshot,
computes deltas, writes latest.json, renders markdown.

Failure modes:
- 404 on a plugin: mark status=missing, continue
- RateLimitError or unhandled exception: bubble up so the workflow exits
  non-zero. We commit nothing in that case (handled by the workflow itself)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from scripts.delta import compute_delta
from scripts.github_api import GitHubClient, RepoData, RepoMissingError
from scripts.metadata import load_metadata
from scripts.models import LatestJson, LatestPlugin, SnapshotRow
from scripts.plugins_yaml import load_registry
from scripts.render import render_all
from scripts.snapshot import read_snapshot, snapshot_path, write_snapshot

log = logging.getLogger(__name__)


class _GH(Protocol):
    def fetch_repo(self, repo: str) -> RepoData: ...


def _prev_date(date: str, days: int) -> str:
    d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from datetime import timedelta
    return (d - timedelta(days=days)).strftime("%Y-%m-%d")


def _read_prev_snapshot(data_dir: Path, today: str, days_back: int) -> list[SnapshotRow] | None:
    path = snapshot_path(data_dir, _prev_date(today, days_back))
    if not path.exists():
        return None
    return read_snapshot(path)


def run_daily(
    main_dir: Path,
    data_dir: Path,
    gh: GitHubClient | _GH,
    today: str,
) -> None:
    registry = load_registry(main_dir / "plugins.yaml")
    metadata = load_metadata(main_dir / "data" / "metadata.json")

    rows: list[SnapshotRow] = []
    missing_ids: set[str] = set()
    archived_ids: set[str] = set()
    repo_data_by_id: dict[str, RepoData] = {}

    for p in registry.plugins:
        try:
            data = gh.fetch_repo(p.repo)
        except RepoMissingError:
            missing_ids.add(p.id)
            continue
        repo_data_by_id[p.id] = data
        if data.archived:
            archived_ids.add(p.id)
        rows.append(SnapshotRow(
            id=p.id, repo=data.repo, stars=data.stars, forks=data.forks,
            open_issues=data.open_issues, archived=data.archived,
            pushed_at=data.pushed_at,
        ))

    write_snapshot(data_dir, today, rows)

    yesterday_rows = _read_prev_snapshot(data_dir, today, 1)
    week_ago_rows = _read_prev_snapshot(data_dir, today, 7)
    delta_24h = compute_delta(rows, yesterday_rows)
    delta_7d = compute_delta(rows, week_ago_rows)
    prev_by_id = {r.id: r.stars for r in yesterday_rows} if yesterday_rows else {}

    plugins_out: list[LatestPlugin] = []
    for p in registry.plugins:
        if p.id in missing_ids:
            plugins_out.append(LatestPlugin(
                id=p.id, repo=p.repo, assistants=p.assistants,
                stars=0, stars_24h=None, stars_7d=None, previous_stars=None,
                archived=False, status="missing",
                url=f"https://github.com/{p.repo}",
            ))
            continue
        d = repo_data_by_id[p.id]
        status = "archived" if d.archived else "ok"
        plugins_out.append(LatestPlugin(
            id=p.id, repo=d.repo, assistants=p.assistants,
            stars=d.stars, stars_24h=delta_24h.get(p.id),
            stars_7d=delta_7d.get(p.id),
            previous_stars=prev_by_id.get(p.id),
            archived=d.archived, status=status,
            url=f"https://github.com/{d.repo}",
        ))

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    latest = LatestJson(generated_at=now_iso, plugins=plugins_out)

    # Persist latest.json
    latest_path = main_dir / "data" / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(
        latest.model_dump(), indent=2, sort_keys=True) + "\n")

    # Render README + rankings/
    rendered = render_all(latest, metadata)
    (main_dir / "README.md").write_text(rendered.readme)
    rankings_dir = main_dir / "rankings"
    rankings_dir.mkdir(exist_ok=True)
    for name, body in rendered.rankings.items():
        (rankings_dir / f"{name}.md").write_text(body)


def main() -> None:
    import os
    import sys

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    main_dir = Path(os.environ.get("MAIN_DIR", "."))
    data_dir = Path(os.environ["DATA_DIR"])
    today = os.environ.get("TODAY") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client = GitHubClient(token=token)
    try:
        run_daily(main_dir, data_dir, client, today=today)
    finally:
        client.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scrape.py -v && mypy scripts/`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape.py tests/test_scrape.py
git commit -m "Daily orchestrator: scrape, snapshot, delta, render"
```

---

## Task 14: Discovery candidate-finder

**Files:**
- Create: `scripts/discover.py`
- Create: `tests/test_discover.py`

- [ ] **Step 1: Write the failing test**

`tests/test_discover.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import respx

from scripts.discover import find_candidates, Candidate


@respx.mock
def test_find_candidates_filters_known_and_small():
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {  # already known — excluded
                    "full_name": "obra/superpowers", "stargazers_count": 1000,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "known",
                },
                {  # too small — excluded
                    "full_name": "tiny/x", "stargazers_count": 3,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "tiny",
                },
                {  # archived — excluded
                    "full_name": "old/y", "stargazers_count": 500,
                    "archived": True, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "archived",
                },
                {  # ✓ candidate
                    "full_name": "newco/cool-plugin", "stargazers_count": 200,
                    "archived": False, "pushed_at": "2026-05-27T00:00:00Z",
                    "description": "Cool",
                },
            ],
        })
    )
    known = {"obra/superpowers"}
    candidates = find_candidates(
        token="t",
        queries=["topic:claude-code-plugin"],
        known_repos=known,
        min_stars=10,
        max_age_days=365,
        today="2026-05-28",
    )
    assert candidates == [Candidate(
        repo="newco/cool-plugin", stars=200,
        description="Cool", assistant_guess="claude-code")]


@respx.mock
def test_find_candidates_skips_stale():
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [{
                "full_name": "stale/x", "stargazers_count": 100,
                "archived": False, "pushed_at": "2024-01-01T00:00:00Z",
                "description": "old",
            }],
        })
    )
    candidates = find_candidates(
        token="t",
        queries=["topic:cursor-extension"],
        known_repos=set(), min_stars=10, max_age_days=365,
        today="2026-05-28",
    )
    assert candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discover.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/discover.py`**

```python
"""Weekly candidate discovery.

Queries GitHub Search for repos matching plugin-shaped patterns; filters by
star count, archive status, and recency. Output is a list of Candidate
objects that the workflow turns into PR body content. Discovery NEVER
auto-adds to plugins.yaml — every entry must pass human review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

# Map search query to the assistant most likely to own a match. A reviewer
# can correct it before merging the PR.
QUERY_TO_ASSISTANT: dict[str, str] = {
    "topic:claude-code-plugin": "claude-code",
    "topic:cursor-extension": "cursor",
    "topic:copilot-extension": "copilot",
    "topic:codex-plugin": "codex",
}


@dataclass(frozen=True)
class Candidate:
    repo: str
    stars: int
    description: str
    assistant_guess: str


def _too_stale(pushed_at: str, today: str, max_age_days: int) -> bool:
    pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    today_dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (today_dt - pushed) > timedelta(days=max_age_days)


def find_candidates(
    token: str,
    queries: list[str],
    known_repos: set[str],
    min_stars: int,
    max_age_days: int,
    today: str,
) -> list[Candidate]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    out: list[Candidate] = []
    seen: set[str] = set()
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30) as c:
        for q in queries:
            resp = c.get("/search/repositories", params={"q": q, "per_page": 50})
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                repo = item["full_name"]
                if repo in known_repos or repo in seen:
                    continue
                if item["stargazers_count"] < min_stars:
                    continue
                if item["archived"]:
                    continue
                if _too_stale(item["pushed_at"], today, max_age_days):
                    continue
                seen.add(repo)
                out.append(Candidate(
                    repo=repo,
                    stars=item["stargazers_count"],
                    description=item.get("description") or "",
                    assistant_guess=QUERY_TO_ASSISTANT.get(q, "claude-code"),
                ))
    return out


def render_candidate_pr_body(candidates: list[Candidate]) -> str:
    """Markdown body for the discovery PR."""
    if not candidates:
        return "No new candidates this week.\n"
    lines = ["Found the following candidates. Move accepted entries into `plugins.yaml`.\n"]
    for c in sorted(candidates, key=lambda x: -x.stars):
        lines.append(
            f"- **{c.repo}** ({c.stars} stars) — _guess: {c.assistant_guess}_  \n"
            f"  {c.description}\n"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_discover.py -v && mypy scripts/`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/discover.py tests/test_discover.py
git commit -m "Candidate discovery with filtering by stars/age/archived"
```

---

## Task 15: Integration test (full pipeline, mocked HTTP)

**Files:**
- Create: `tests/test_integration.py`
- Create: `tests/fixtures/integration-plugins.yaml`

- [ ] **Step 1: Create fixture**

`tests/fixtures/integration-plugins.yaml`:

```yaml
plugins:
  - id: alpha
    repo: o/alpha
    assistants: [claude-code]
    added: "2026-05-28"
  - id: beta
    repo: o/beta
    assistants: [cursor]
    added: "2026-05-28"
  - id: gamma
    repo: o/gamma
    assistants: [cursor, claude-code]
    added: "2026-05-28"
```

- [ ] **Step 2: Write the integration test**

`tests/test_integration.py`:

```python
"""End-to-end test: feed a fixture plugins.yaml + mocked GitHub responses;
assert all output files exist and contain expected content. This is the
final safety net — if every unit test passes but this one fails, the wiring
between modules is broken."""
import json
import shutil
from pathlib import Path

import httpx
import respx

from scripts.github_api import GitHubClient
from scripts.scrape import run_daily

FIXTURES = Path(__file__).parent / "fixtures"


@respx.mock
def test_full_daily_pipeline(tmp_path: Path):
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    shutil.copy(FIXTURES / "integration-plugins.yaml", main_dir / "plugins.yaml")

    def _repo(name: str, stars: int) -> httpx.Response:
        return httpx.Response(200, json={
            "full_name": name, "stargazers_count": stars,
            "forks_count": 1, "open_issues_count": 0, "archived": False,
            "pushed_at": "2026-05-27T00:00:00Z",
        })

    respx.get("https://api.github.com/repos/o/alpha").mock(return_value=_repo("o/alpha", 100))
    respx.get("https://api.github.com/repos/o/beta").mock(return_value=_repo("o/beta", 50))
    respx.get("https://api.github.com/repos/o/gamma").mock(return_value=_repo("o/gamma", 200))

    gh = GitHubClient(token="t")
    try:
        run_daily(main_dir, data_dir, gh, today="2026-05-28")
    finally:
        gh.close()

    # Files exist
    assert (main_dir / "README.md").exists()
    assert (main_dir / "data" / "latest.json").exists()
    assert (data_dir / "snapshots" / "2026-05-28.jsonl").exists()
    assert (main_dir / "rankings" / "claude-code.md").exists()
    assert (main_dir / "rankings" / "cursor.md").exists()
    assert (main_dir / "rankings" / "all.md").exists()
    assert (main_dir / "rankings" / "trending.md").exists()

    # latest.json correctly populated
    latest = json.loads((main_dir / "data" / "latest.json").read_text())
    by_id = {p["id"]: p for p in latest["plugins"]}
    assert by_id["alpha"]["stars"] == 100
    assert by_id["gamma"]["stars"] == 200
    # No previous snapshot → deltas are None
    assert by_id["alpha"]["stars_24h"] is None

    # Snapshot is one line per plugin
    snapshot_lines = (data_dir / "snapshots" / "2026-05-28.jsonl").read_text().splitlines()
    assert len(snapshot_lines) == 3

    # gamma appears in BOTH claude-code.md and cursor.md
    assert "gamma" in (main_dir / "rankings" / "claude-code.md").read_text()
    assert "gamma" in (main_dir / "rankings" / "cursor.md").read_text()
    # but beta only in cursor.md, alpha only in claude-code.md
    assert "alpha" not in (main_dir / "rankings" / "cursor.md").read_text()
    assert "beta" not in (main_dir / "rankings" / "claude-code.md").read_text()


@respx.mock
def test_full_pipeline_idempotent(tmp_path: Path):
    """Running the daily pipeline twice produces the same snapshot file
    and the same rankings markdown."""
    main_dir = tmp_path / "main"
    data_dir = tmp_path / "data"
    main_dir.mkdir()
    data_dir.mkdir()
    shutil.copy(FIXTURES / "integration-plugins.yaml", main_dir / "plugins.yaml")

    for name in ("alpha", "beta", "gamma"):
        respx.get(f"https://api.github.com/repos/o/{name}").mock(return_value=httpx.Response(
            200, json={
                "full_name": f"o/{name}", "stargazers_count": 100,
                "forks_count": 0, "open_issues_count": 0, "archived": False,
                "pushed_at": "2026-05-27T00:00:00Z",
            }))

    gh = GitHubClient(token="t")
    try:
        run_daily(main_dir, data_dir, gh, today="2026-05-28")
        snap1 = (data_dir / "snapshots" / "2026-05-28.jsonl").read_bytes()
        all1 = (main_dir / "rankings" / "all.md").read_bytes()

        run_daily(main_dir, data_dir, gh, today="2026-05-28")
        snap2 = (data_dir / "snapshots" / "2026-05-28.jsonl").read_bytes()
        all2 = (main_dir / "rankings" / "all.md").read_bytes()
    finally:
        gh.close()

    assert snap1 == snap2
    assert all1 == all2
```

- [ ] **Step 3: Run the test**

Run: `pytest tests/test_integration.py -v`
Expected: 2 passed.

- [ ] **Step 4: Run the full suite to confirm nothing else broke**

Run: `pytest -v && mypy scripts/ tests/ && ruff check .`
Expected: all tests pass, mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py tests/fixtures/integration-plugins.yaml
git commit -m "Integration test: full daily pipeline with mocked HTTP"
```

---

## Task 16: Seed plugins.yaml

**Files:**
- Create: `plugins.yaml` (at repo root, not the fixtures one)

- [ ] **Step 1: Create the initial seed**

`plugins.yaml`:

```yaml
# Curated registry of AI coding assistant plugins.
# To add a plugin: open a PR adding an entry below.
# Fields:
#   id:         stable slug (kebab-case, never renamed)
#   repo:       GitHub "owner/name"
#   assistants: one or more of [claude-code, cursor, copilot, codex]
#   added:      YYYY-MM-DD date this entry was added

plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
```

Start with just one known-good entry. The maintainer adds more after the first successful daily run confirms the pipeline works end-to-end. Discovery workflow (Task 19) will surface candidates each week.

- [ ] **Step 2: Validate it locally**

Run:
```bash
python -c "from scripts.plugins_yaml import load_registry; from pathlib import Path; r = load_registry(Path('plugins.yaml')); print(f'{len(r.plugins)} plugin(s)')"
```
Expected: `1 plugin(s)`

- [ ] **Step 3: Commit**

```bash
git add plugins.yaml
git commit -m "Seed plugins.yaml with superpowers"
```

---

## Task 17: Initialize the data branch

**Files:**
- Create (on `data` orphan branch): `README.md`, `.gitignore`

- [ ] **Step 1: Create the orphan branch**

Run from repo root:
```bash
git checkout --orphan data
git rm -rf . 2>/dev/null || true
```

You will be on `data` with no files. Confirm with `git status`.

- [ ] **Step 2: Create a minimal README explaining the branch**

`README.md`:

```markdown
# data branch

Append-only daily snapshots for the AI Plugin Rankings repo.

## Format

`snapshots/YYYY-MM-DD.jsonl` — one line per plugin, JSONL:

```json
{"id":"superpowers","repo":"obra/superpowers","stars":1247,"forks":89,"open_issues":12,"archived":false,"pushed_at":"2026-05-27T18:22:00Z"}
```

Files are written by the daily GitHub Actions workflow on the `main` branch.
This branch has no shared history with `main` (it's an orphan branch) so it
can grow indefinitely without bloating the main checkout.
```

`.gitignore`:

```
.DS_Store
```

- [ ] **Step 3: Commit the empty data branch**

```bash
git add README.md .gitignore
git commit -m "Initialize data branch for snapshot history"
```

- [ ] **Step 4: Return to main**

```bash
git checkout main
```

Confirm `git branch` shows both `main` and `data`. Confirm the `main` checkout no longer has `data` branch's files.

---

## Task 18: CI workflow (PR gates)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install
        run: pip install -e ".[dev]"

      - name: Lint
        run: ruff check .

      - name: Type check
        run: mypy scripts tests

      - name: Test
        run: pytest -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "CI: ruff + mypy + pytest on PRs and main pushes"
```

---

## Task 19: Daily cron workflow

**Files:**
- Create: `.github/workflows/daily.yml`

- [ ] **Step 1: Create the workflow**

`.github/workflows/daily.yml`:

```yaml
name: Daily ranking update

on:
  schedule:
    - cron: "0 3 * * *"  # 03:00 UTC
  workflow_dispatch:     # allow manual trigger from the Actions UI

permissions:
  contents: write
  issues: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout main
        uses: actions/checkout@v4
        with:
          path: main

      - name: Checkout data branch
        uses: actions/checkout@v4
        with:
          ref: data
          path: data

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
          cache-dependency-path: main/pyproject.toml

      - name: Install
        working-directory: main
        run: pip install -e .

      - name: Configure git
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

      - name: Run daily pipeline
        working-directory: main
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          MAIN_DIR: ${{ github.workspace }}/main
          DATA_DIR: ${{ github.workspace }}/data
        run: python -m scripts.scrape

      - name: Commit snapshot to data branch
        working-directory: data
        run: |
          git add snapshots/
          if git diff --cached --quiet; then
            echo "No snapshot changes (unexpected)."
          else
            git commit -m "Snapshot $(date -u +%Y-%m-%d)"
            git push origin data
          fi

      - name: Commit rankings to main
        working-directory: main
        run: |
          git add README.md rankings/ data/latest.json
          if git diff --cached --quiet; then
            echo "No ranking changes."
          else
            git commit -m "Daily update $(date -u +%Y-%m-%d)"
            git push origin main
          fi

      - name: Open issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const today = new Date().toISOString().slice(0,10);
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `Daily run failed: ${today}`,
              body: `The daily ranking workflow failed. See: ${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`,
              labels: ['cron-failure'],
            });
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily.yml
git commit -m "Daily cron: scrape, snapshot to data branch, render to main"
```

---

## Task 20: Weekly enrichment workflow

**Files:**
- Create: `.github/workflows/weekly-enrich.yml`

- [ ] **Step 1: Create the workflow**

`.github/workflows/weekly-enrich.yml`:

```yaml
name: Weekly enrichment

on:
  schedule:
    - cron: "0 4 * * 0"  # Sundays 04:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  issues: write

jobs:
  enrich:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install
        run: pip install -e .

      - name: Configure git
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

      - name: Run weekly enrichment
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python -c "
          import os
          from datetime import datetime, timezone
          from pathlib import Path
          from scripts.anthropic_client import AnthropicEnricher
          from scripts.enrich import enrich_registry
          from scripts.github_api import GitHubClient

          gh = GitHubClient(token=os.environ['GITHUB_TOKEN'])
          enricher = AnthropicEnricher(api_key=os.environ['ANTHROPIC_API_KEY'])
          now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
          try:
              enrich_registry(
                  Path('plugins.yaml'), Path('data/metadata.json'),
                  gh, enricher, now=now,
              )
          finally:
              gh.close()
          "

      - name: Commit metadata if changed
        run: |
          git add data/metadata.json
          if git diff --cached --quiet; then
            echo "No metadata changes."
          else
            git commit -m "Weekly enrichment $(date -u +%Y-%m-%d)"
            git push origin main
          fi

      - name: Open issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const today = new Date().toISOString().slice(0,10);
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `Weekly enrichment failed: ${today}`,
              body: `See: ${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`,
              labels: ['cron-failure'],
            });
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/weekly-enrich.yml
git commit -m "Weekly enrichment cron: LLM descriptions/tags via Anthropic"
```

**Note for the maintainer:** before the first run, add an `ANTHROPIC_API_KEY` secret in repo Settings → Secrets and variables → Actions.

---

## Task 21: Weekly discovery workflow

**Files:**
- Create: `.github/workflows/discover.yml`
- Create: `scripts/run_discover.py` (thin entry point that opens the PR)

- [ ] **Step 1: Create the entry script**

`scripts/run_discover.py`:

```python
"""Run discovery and open a PR with candidates.

Called by the weekly-discover workflow. Reads plugins.yaml to build the
known-repos set, runs find_candidates, writes a markdown PR body, and
exits. The workflow itself uses the body to open the PR."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.discover import QUERY_TO_ASSISTANT, find_candidates, render_candidate_pr_body
from scripts.plugins_yaml import load_registry


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    registry = load_registry(Path("plugins.yaml"))
    known = {p.repo for p in registry.plugins}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    candidates = find_candidates(
        token=token,
        queries=list(QUERY_TO_ASSISTANT.keys()),
        known_repos=known,
        min_stars=10,
        max_age_days=365,
        today=today,
    )

    body = render_candidate_pr_body(candidates)
    Path("candidates-body.md").write_text(body)
    # Print "true" to stdout if there are candidates; the workflow gates the
    # PR-creation step on this so we never open an empty PR.
    print("has_candidates=" + ("true" if candidates else "false"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the workflow**

`.github/workflows/discover.yml`:

```yaml
name: Weekly discovery

on:
  schedule:
    - cron: "0 5 * * 0"  # Sundays 05:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install
        run: pip install -e .

      - name: Run discovery
        id: run
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python -m scripts.run_discover | tee -a $GITHUB_OUTPUT

      - name: Open PR
        if: steps.run.outputs.has_candidates == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          DATE=$(date -u +%Y-%m-%d)
          BRANCH="discover/${DATE}"
          git config --global user.name "github-actions[bot]"
          git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git checkout -b "$BRANCH"
          # No code changes; PR is informational only. Push an empty commit so the PR can exist.
          git commit --allow-empty -m "Discovery candidates: ${DATE}"
          git push origin "$BRANCH"
          gh pr create \
            --title "Discovered candidates: ${DATE}" \
            --body-file candidates-body.md \
            --base main \
            --head "$BRANCH" \
            --label discovery
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_discover.py .github/workflows/discover.yml
git commit -m "Weekly discovery cron with informational PR"
```

---

## Task 22: End-to-end local dry run + final verification

This task verifies the whole system works against real APIs locally before any cron fires.

- [ ] **Step 1: Run the full test suite one more time**

Run from repo root:
```bash
. .venv/bin/activate
ruff check .
mypy scripts tests
pytest -v
```

Expected: ruff clean, mypy clean, all tests passing.

- [ ] **Step 2: Local smoke test against the real GitHub API**

Set up a sibling `data/` directory (simulating the data branch checkout that CI does):

```bash
mkdir -p /tmp/ai-plugin-rankings-data/snapshots
```

Run the daily pipeline against the real GitHub API (uses your local `GITHUB_TOKEN`):

```bash
GITHUB_TOKEN=$(gh auth token) \
MAIN_DIR=. \
DATA_DIR=/tmp/ai-plugin-rankings-data \
python -m scripts.scrape
```

Expected: exits 0. Inspect the produced files:
- `README.md` — should have the top-N tables (just `superpowers` for now)
- `rankings/claude-code.md` — should include `superpowers`
- `rankings/cursor.md` — should exist but show 0 plugins
- `data/latest.json` — `stars_24h` should be `null` (no previous snapshot)
- `/tmp/ai-plugin-rankings-data/snapshots/<TODAY>.jsonl` — one line for `superpowers`

If any of those look wrong, debug before proceeding.

- [ ] **Step 3: Revert local changes from the smoke test**

The smoke run wrote real files (`README.md`, `rankings/`, `data/latest.json`) into the working tree. Don't commit them — they'll be regenerated by the first real cron run with proper timestamps and proper data branch integration.

Run:
```bash
git checkout -- README.md
rm -rf rankings/ data/
```

Confirm `git status` shows a clean tree apart from the (intended) absence of generated files.

- [ ] **Step 4: Push to GitHub (manual step for the maintainer)**

This is the human handoff. The maintainer must:

1. Create a GitHub repo (e.g. `<owner>/ai-plugin-rankings`)
2. `git remote add origin git@github.com:<owner>/ai-plugin-rankings.git`
3. `git push -u origin main`
4. `git push origin data`
5. In repo Settings → Secrets and variables → Actions, add `ANTHROPIC_API_KEY`
6. Trigger the daily workflow manually once (Actions tab → "Daily ranking update" → Run workflow) to confirm it works before the first cron fires

This step is documented but not automated — pushing a brand-new repo requires human authentication and a remote choice.

- [ ] **Step 5: Final commit (none required for this task)**

This task is verification + handoff documentation; nothing to commit.

---

## Self-Review (post-write check)

Cross-checked the plan against the spec:

| Spec section | Implementing tasks |
|---|---|
| Repo layout | T1 (skeleton), T16 (plugins.yaml seed), T17 (data branch) |
| Data model: PluginEntry / Registry | T3 (models), T4 (loader) |
| Data model: MetadataEntry | T3, T6 |
| Data model: SnapshotRow | T3, T5 |
| Data model: LatestPlugin / LatestJson | T3 |
| Daily pipeline | T7 (GitHub), T8 (delta), T9 (rank), T10 (render), T13 (orchestrator), T15 (integration), T19 (workflow) |
| Weekly enrichment | T11 (Anthropic client), T12 (orchestrator), T20 (workflow) |
| Weekly discovery | T14 (discover), T21 (workflow + PR opener) |
| Error handling: 404 / 5xx / 403 / archived | T7, T13 |
| Error handling: LLM bad JSON | T11, T12 |
| Determinism guarantees | T5, T6, T10 |
| Testing strategy | each task includes unit tests; T15 covers integration; T18 (CI) enforces gates |

No placeholders remaining. No "implement later" or "add appropriate handling." Every code step has runnable code.

Type / signature consistency verified across tasks:
- `RepoData` defined in T7, consumed in T13 — signature matches
- `LatestPlugin` shape defined in T3, used identically in T9/T10/T13
- `EnrichmentResult` defined in T11, consumed by T12 — matches
- `Candidate` defined in T14, consumed by T21's `run_discover.py` — matches
- `render_all` in T10 returns `RenderOutput` with `readme` and `rankings: dict[str, str]`; T13 destructures correctly
- `compute_delta` returns `dict[str, int | None]`; consumed by T13 via `.get(p.id)` which yields the same type

---

## Notes for the executor

- **TDD discipline:** every implementation step is preceded by a failing test. If a test "accidentally" passes before implementation, the test is wrong — investigate.
- **Determinism:** several files (snapshots, metadata, rendered markdown) are byte-deterministic by design. If golden-file tests start failing on a no-op change, you've broken determinism — fix the root cause, don't relax the test.
- **No live API calls in CI.** Task 22 includes a smoke test that does hit real APIs, but only locally. Don't add a CI step that calls Anthropic or unmocked GitHub.
- **`scripts.scrape.main()`** is the daily entry point (used by the workflow as `python -m scripts.scrape`). `scripts.run_discover.main()` is the discovery entry. The weekly-enrich workflow inlines its entry as a `python -c` block to avoid one more file.
