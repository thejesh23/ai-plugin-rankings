# Bulk Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 candidate-PR discovery flow with a multi-source aggregator that auto-commits every repo with ≥1000 stars directly to `plugins.yaml`.

**Architecture:** Pluggable `Source` adapters under `scripts/sources/`, one per data source. A rewritten `scripts/discover.py` orchestrator runs them all, dedupes by repo, hits GitHub for canonical star counts via the existing `github_api.py`, applies the ≥1000-star + non-archived filter, resolves multi-assistant tags by README grep, appends new entries to `plugins.yaml` (via `ruamel.yaml` to preserve comments), writes an audit line to `discovery.log`, and commits to `main`.

**Tech Stack:** Python 3.12, `httpx`, `pydantic` v2, `ruamel.yaml` (new), `beautifulsoup4` (new), `anthropic` (unused for this feature), `pytest` + `respx`, `ruff`, `mypy --strict`.

**Repo root:** `/Users/thejesh/Git/ai-plugin-rankings` — currently on `main`, all 22 v1 tasks done, registry has 12 entries.

**Spec reference:** `docs/superpowers/specs/2026-05-29-bulk-discovery-design.md`

---

## Task 1: Add new dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add ruamel.yaml and beautifulsoup4 to runtime deps**

Edit `pyproject.toml`. Change the `dependencies` block from:

```toml
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "anthropic>=0.40",
]
```

to:

```toml
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "anthropic>=0.40",
    "ruamel.yaml>=0.18",
    "beautifulsoup4>=4.12",
]
```

Add `types-beautifulsoup4` to the `dev` block:

```toml
dev = [
    "pytest>=8.0",
    "respx>=0.21",
    "ruff>=0.5",
    "mypy>=1.10",
    "types-PyYAML",
    "types-beautifulsoup4",
]
```

- [ ] **Step 2: Install and verify**

Run:
```bash
source .venv/bin/activate
pip install -e ".[dev]" --quiet
ruff check . && mypy scripts tests && pytest -q
```

Expected: install succeeds; 55 tests pass; mypy/ruff clean.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "Add ruamel.yaml and beautifulsoup4 for bulk discovery"
```

---

## Task 2: Source protocol and RawCandidate

**Files:**
- Create: `scripts/sources/__init__.py` (empty)
- Create: `scripts/sources/base.py`
- Create: `tests/sources/__init__.py` (empty)
- Create: `tests/sources/test_base.py`

- [ ] **Step 1: Create package marker files**

Run:
```bash
mkdir -p scripts/sources tests/sources
touch scripts/sources/__init__.py tests/sources/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/sources/test_base.py`:

```python
from scripts.sources.base import RawCandidate


def test_raw_candidate_is_frozen_dataclass() -> None:
    c = RawCandidate(
        repo="obra/superpowers",
        source="github_topic_search",
        hint_assistants=["claude-code"],
    )
    assert c.repo == "obra/superpowers"
    assert c.source == "github_topic_search"
    assert c.hint_assistants == ["claude-code"]


def test_raw_candidate_equality() -> None:
    a = RawCandidate(repo="o/x", source="s", hint_assistants=["claude-code"])
    b = RawCandidate(repo="o/x", source="s", hint_assistants=["claude-code"])
    assert a == b
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/sources/test_base.py -v`
Expected: FAIL — `scripts.sources.base` missing.

- [ ] **Step 4: Implement `scripts/sources/base.py`**

```python
"""Source protocol and RawCandidate dataclass.

Each discovery source implements `Source` to yield `RawCandidate`s. Sources
emit only repo + source name + hint about target assistant(s). The
orchestrator fetches canonical star counts separately so multi-source hits
on the same repo only cost one API call."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class RawCandidate:
    repo: str               # "owner/name"
    source: str             # adapter name (for dedupe attribution + logs)
    hint_assistants: list[str]


class Source(Protocol):
    name: str
    default_assistant: str

    def fetch_candidates(self) -> Iterable[RawCandidate]: ...
```

- [ ] **Step 5: Run tests + gates**

Run: `pytest tests/sources/test_base.py -v && mypy scripts tests && ruff check .`
Expected: 2 passed, mypy + ruff clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/sources/ tests/sources/
git commit -m "Source protocol and RawCandidate dataclass"
```

---

## Task 3: ID generation helper

**Files:**
- Create: `scripts/id_gen.py`
- Create: `tests/test_id_gen.py`

- [ ] **Step 1: Write the failing test**

`tests/test_id_gen.py`:

```python
from scripts.id_gen import generate_id


def test_simple_slug() -> None:
    assert generate_id("obra/superpowers", set()) == "superpowers"


def test_lowercase_and_hyphens() -> None:
    assert generate_id("Some/Cool_Tool.Name", set()) == "cool-tool-name"


def test_collision_appends_owner() -> None:
    assert generate_id("alice/utils", {"utils"}) == "alice-utils"


def test_double_collision_appends_hash() -> None:
    out = generate_id("alice/utils", {"utils", "alice-utils"})
    assert out.startswith("alice-utils-")
    assert len(out) == len("alice-utils-") + 4


def test_deterministic_across_calls() -> None:
    a = generate_id("alice/utils", {"utils", "alice-utils"})
    b = generate_id("alice/utils", {"utils", "alice-utils"})
    assert a == b


def test_handles_dots_and_underscores() -> None:
    assert generate_id("org/my.cool_thing", set()) == "my-cool-thing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_id_gen.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/id_gen.py`**

```python
"""Generate stable kebab-case slug IDs for plugins.yaml entries.

The id is derived from the repo name only. Collisions are resolved by
prepending the owner; double collisions by appending a 4-char hash of the
full repo. Deterministic: same repo + same existing_ids always yields the
same id."""
from __future__ import annotations

import hashlib
import re


def generate_id(repo: str, existing_ids: set[str]) -> str:
    owner, name = repo.split("/")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if slug and slug not in existing_ids:
        return slug
    qualified = f"{owner.lower()}-{slug}" if slug else owner.lower()
    if qualified not in existing_ids:
        return qualified
    suffix = hashlib.sha1(repo.encode()).hexdigest()[:4]
    return f"{qualified}-{suffix}"
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/test_id_gen.py -v && mypy scripts tests && ruff check .`
Expected: 6 passed, clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/id_gen.py tests/test_id_gen.py
git commit -m "Deterministic ID slug generator with collision handling"
```

---

## Task 4: YAML writer with comment preservation

**Files:**
- Create: `scripts/yaml_writer.py`
- Create: `tests/test_yaml_writer.py`

- [ ] **Step 1: Write the failing test**

`tests/test_yaml_writer.py`:

```python
from pathlib import Path

from scripts.models import PluginEntry
from scripts.yaml_writer import append_plugins_to_yaml


SEED_YAML = """\
# Curated registry of AI coding assistant plugins.
# To add a plugin: open a PR adding an entry below.

plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
"""


def test_append_preserves_header_comment(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(SEED_YAML)
    entry = PluginEntry(
        id="newone", repo="o/newone", assistants=["cursor"], added="2026-05-29",
    )
    append_plugins_to_yaml(p, [entry])
    content = p.read_text()
    assert "# Curated registry" in content
    assert "# To add a plugin" in content
    assert "newone" in content


def test_append_adds_entries_to_plugins_list(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(SEED_YAML)
    entries = [
        PluginEntry(id="a", repo="o/a", assistants=["cursor"], added="2026-05-29"),
        PluginEntry(id="b", repo="o/b", assistants=["claude-code", "codex"],
                    added="2026-05-29"),
    ]
    append_plugins_to_yaml(p, entries)
    from scripts.plugins_yaml import load_registry
    reg = load_registry(p)
    assert [pl.id for pl in reg.plugins] == ["superpowers", "a", "b"]
    assert reg.plugins[2].assistants == ["claude-code", "codex"]


def test_append_empty_list_no_change(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(SEED_YAML)
    before = p.read_text()
    append_plugins_to_yaml(p, [])
    assert p.read_text() == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_yaml_writer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/yaml_writer.py`**

```python
"""Append plugin entries to plugins.yaml while preserving the header comments.

PyYAML strips comments on dump; ruamel.yaml round-trips them. Existing
`scripts/plugins_yaml.py` is read-only and continues to use PyYAML for
validation."""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from scripts.models import PluginEntry

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def append_plugins_to_yaml(path: Path, new_entries: list[PluginEntry]) -> None:
    """Append new_entries to the `plugins` list in the YAML file. No-op if empty."""
    if not new_entries:
        return
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    for entry in new_entries:
        data["plugins"].append({
            "id": entry.id,
            "repo": entry.repo,
            "assistants": entry.assistants,
            "added": entry.added,
        })
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/test_yaml_writer.py -v && mypy scripts tests && ruff check .`
Expected: 3 passed.

If mypy complains about `_yaml.load(f)` returning `Any`, add `# type: ignore[no-any-return]` only if needed. The pydantic round-trip via `load_registry` in test_append_adds_entries_to_plugins_list provides downstream type safety.

- [ ] **Step 5: Commit**

```bash
git add scripts/yaml_writer.py tests/test_yaml_writer.py
git commit -m "YAML writer with comment-preserving append via ruamel.yaml"
```

---

## Task 5: GitHub code search source

**Files:**
- Create: `scripts/sources/github_code_search.py`
- Create: `tests/sources/test_github_code_search.py`

- [ ] **Step 1: Write the failing test**

`tests/sources/test_github_code_search.py`:

```python
import httpx
import respx

from scripts.sources.github_code_search import GithubCodeSearchSource


@respx.mock
def test_emits_repos_from_code_search() -> None:
    # We intercept any /search/code call and return two hits.
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"repository": {"full_name": "alice/plugin1"}},
                {"repository": {"full_name": "bob/plugin2"}},
            ],
        })
    )
    src = GithubCodeSearchSource(token="t")
    results = list(src.fetch_candidates())
    repos = {c.repo for c in results}
    assert "alice/plugin1" in repos
    assert "bob/plugin2" in repos
    # Every candidate carries the source name
    assert all(c.source == "github_code_search" for c in results)


@respx.mock
def test_empty_response_emits_nothing() -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    src = GithubCodeSearchSource(token="t")
    assert list(src.fetch_candidates()) == []


@respx.mock
def test_http_error_logged_emits_nothing(caplog) -> None:  # type: ignore[no-untyped-def]
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(422, json={"message": "bad query"})
    )
    src = GithubCodeSearchSource(token="t")
    # One source-level failure should not raise.
    results = list(src.fetch_candidates())
    assert results == []


@respx.mock
def test_dedupes_within_source() -> None:
    """Multiple queries hitting the same repo only yield one RawCandidate."""
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"repository": {"full_name": "alice/plugin1"}},
                {"repository": {"full_name": "alice/plugin1"}},
            ],
        })
    )
    src = GithubCodeSearchSource(token="t")
    results = list(src.fetch_candidates())
    assert len(results) == sum(1 for _ in src._QUERIES)
    # All for the same repo so set of repos has length 1
    assert {c.repo for c in results} == {"alice/plugin1"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_github_code_search.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scripts/sources/github_code_search.py`**

```python
"""GitHub code search for plugin manifest filenames.

Searches for files that are distinctive to each ecosystem (e.g.
`.claude-plugin.json`, `.cursorrules`). Code search rate limit is 30/min
which is fine at 7 queries/week."""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)


class GithubCodeSearchSource:
    name = "github_code_search"
    default_assistant = "claude-code"

    # (query string, hint assistant)
    _QUERIES: tuple[tuple[str, str], ...] = (
        ("filename:.claude-plugin.json", "claude-code"),
        ("filename:claude-plugin.json", "claude-code"),
        ("filename:.cursorrules", "cursor"),
        ("filename:cursor.json path:.cursor", "cursor"),
        ("filename:codex-plugin.toml", "codex"),
        ("filename:codex.toml", "codex"),
        ("filename:copilot-extension.json", "copilot"),
    )

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            for query, hint in self._QUERIES:
                try:
                    resp = c.get("/search/code", params={"q": query, "per_page": 100})
                    resp.raise_for_status()
                except httpx.HTTPError:
                    log.warning("code search query failed: %r", query)
                    continue
                for item in resp.json().get("items", []):
                    repo = item["repository"]["full_name"]
                    yield RawCandidate(
                        repo=repo, source=self.name, hint_assistants=[hint],
                    )
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/sources/test_github_code_search.py -v && mypy scripts tests && ruff check .`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/github_code_search.py tests/sources/test_github_code_search.py
git commit -m "Source: GitHub code search for plugin manifest filenames"
```

---

## Task 6: GitHub topic + name search source

**Files:**
- Create: `scripts/sources/github_topic_search.py`
- Create: `tests/sources/test_github_topic_search.py`

- [ ] **Step 1: Write the failing test**

`tests/sources/test_github_topic_search.py`:

```python
import httpx
import respx

from scripts.sources.github_topic_search import GithubTopicSearchSource


@respx.mock
def test_emits_repos_from_topic_search() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"full_name": "alice/p1"},
                {"full_name": "bob/p2"},
            ],
        })
    )
    src = GithubTopicSearchSource(token="t")
    results = list(src.fetch_candidates())
    assert {c.repo for c in results} >= {"alice/p1", "bob/p2"}
    assert all(c.source == "github_topic_search" for c in results)


@respx.mock
def test_each_query_uses_correct_hint() -> None:
    """A topic query has a known assistant hint."""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={"items": [{"full_name": "x/y"}]})
    )
    src = GithubTopicSearchSource(token="t")
    by_hint: dict[str, set[str]] = {}
    for c in src.fetch_candidates():
        for h in c.hint_assistants:
            by_hint.setdefault(h, set()).add(c.repo)
    # The hint set must equal the assistants we declared in _QUERIES.
    assert by_hint.keys() == {h for _, h in src._QUERIES}


@respx.mock
def test_empty_response_emits_nothing() -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    src = GithubTopicSearchSource(token="t")
    assert list(src.fetch_candidates()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_github_topic_search.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/sources/github_topic_search.py`**

```python
"""Expanded GitHub topic + in:name search for AI assistant plugins."""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)


class GithubTopicSearchSource:
    name = "github_topic_search"
    default_assistant = "claude-code"

    _QUERIES: tuple[tuple[str, str], ...] = (
        ("topic:claude-code-plugin", "claude-code"),
        ("topic:claude-skills", "claude-code"),
        ("topic:claude-code", "claude-code"),
        ("topic:cursor-rules", "cursor"),
        ("topic:cursor-extension", "cursor"),
        ("topic:cursorrules", "cursor"),
        ("topic:copilot-extension", "copilot"),
        ("topic:github-copilot-extension", "copilot"),
        ("topic:codex-plugin", "codex"),
        ("topic:codex-extension", "codex"),
        ("topic:mcp-server", "claude-code"),
        ("in:name claude-code stars:>10", "claude-code"),
        ("in:name cursor-rules stars:>10", "cursor"),
    )

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            for query, hint in self._QUERIES:
                try:
                    resp = c.get(
                        "/search/repositories",
                        params={"q": query, "per_page": 100},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    log.warning("topic search query failed: %r", query)
                    continue
                for item in resp.json().get("items", []):
                    yield RawCandidate(
                        repo=item["full_name"],
                        source=self.name,
                        hint_assistants=[hint],
                    )
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/sources/test_github_topic_search.py -v && mypy scripts tests && ruff check .`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/github_topic_search.py tests/sources/test_github_topic_search.py
git commit -m "Source: expanded GitHub topic + in:name search"
```

---

## Task 7: Awesome-list source

**Files:**
- Create: `scripts/sources/awesome_list.py`
- Create: `tests/sources/test_awesome_list.py`

- [ ] **Step 1: Write the failing test**

`tests/sources/test_awesome_list.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_awesome_list.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/sources/awesome_list.py`**

```python
"""Parse READMEs of curated awesome-* lists; extract every github.com link."""
from __future__ import annotations

import base64
import logging
import re
from typing import Iterable

import httpx

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

DEFAULT_LISTS: list[tuple[str, str]] = [
    ("ComposioHQ/awesome-claude-plugins", "claude-code"),
    ("ccplugins/awesome-claude-code-plugins", "claude-code"),
    ("quemsah/awesome-claude-plugins", "claude-code"),
]

_GH_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)",
)


class AwesomeListSource:
    name = "awesome_list"
    default_assistant = "claude-code"

    def __init__(
        self,
        token: str,
        lists: list[tuple[str, str]] | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._lists = lists if lists is not None else DEFAULT_LISTS

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            for list_repo, hint in self._lists:
                try:
                    resp = c.get(f"/repos/{list_repo}/readme")
                except httpx.HTTPError:
                    log.warning("could not fetch %s", list_repo)
                    continue
                if resp.status_code == 404:
                    log.warning("no README for %s", list_repo)
                    continue
                if not resp.is_success:
                    log.warning("readme fetch failed for %s: %d", list_repo, resp.status_code)
                    continue
                body = resp.json()
                if body.get("encoding") != "base64":
                    continue
                text = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
                seen: set[str] = set()
                for m in _GH_URL_RE.finditer(text):
                    owner, name = m.group(1), m.group(2)
                    name = name.rstrip(".")  # strip trailing punctuation
                    repo = f"{owner}/{name}"
                    if repo == list_repo:
                        continue
                    if repo in seen:
                        continue
                    seen.add(repo)
                    yield RawCandidate(
                        repo=repo, source=self.name, hint_assistants=[hint],
                    )
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/sources/test_awesome_list.py -v && mypy scripts tests && ruff check .`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/awesome_list.py tests/sources/test_awesome_list.py
git commit -m "Source: parse awesome-* list READMEs for GitHub links"
```

---

## Task 8: Codex marketplace source

**Files:**
- Create: `scripts/sources/codex_marketplace.py`
- Create: `tests/sources/test_codex_marketplace.py`

- [ ] **Step 1: Write the failing test**

`tests/sources/test_codex_marketplace.py`:

```python
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
    # Repo name contains "claude" → also hints claude-code.
    assert set(by_repo["bob/claude-plugin"].hint_assistants) == {"codex", "claude-code"}


@respx.mock
def test_failed_fetch_emits_nothing() -> None:
    respx.get("https://www.codex-marketplace.com/plugins").mock(
        return_value=httpx.Response(500)
    )
    src = CodexMarketplaceSource()
    assert list(src.fetch_candidates()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_codex_marketplace.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/sources/codex_marketplace.py`**

```python
"""Scrape codex-marketplace.com/plugins for GitHub repo links."""
from __future__ import annotations

import logging
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

URL = "https://www.codex-marketplace.com/plugins"
_GH_URL_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/?$",
)
USER_AGENT = "ai-plugin-rankings-bot/1.0"


class CodexMarketplaceSource:
    name = "codex_marketplace"
    default_assistant = "codex"

    def __init__(self, url: str = URL) -> None:
        self._url = url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        try:
            resp = httpx.get(self._url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            log.warning("codex-marketplace fetch failed")
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = _GH_URL_RE.match(href.rstrip("/"))
            if not m:
                continue
            repo = f"{m.group(1)}/{m.group(2)}"
            if repo in seen:
                continue
            seen.add(repo)
            hints = ["codex"]
            if "claude" in m.group(2).lower():
                hints.append("claude-code")
            yield RawCandidate(
                repo=repo, source=self.name, hint_assistants=hints,
            )
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/sources/test_codex_marketplace.py -v && mypy scripts tests && ruff check .`
Expected: 3 passed.

If mypy complains about `a["href"]` (bs4 stubs return `str | list[str]`), add `# type: ignore[index]` or wrap in `str()`.

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/codex_marketplace.py tests/sources/test_codex_marketplace.py
git commit -m "Source: codex-marketplace.com HTML scrape"
```

---

## Task 9: Claude marketplaces source

**Files:**
- Create: `scripts/sources/claude_marketplaces.py`
- Create: `tests/sources/test_claude_marketplaces.py`

- [ ] **Step 1: Write the failing test**

`tests/sources/test_claude_marketplaces.py`:

```python
import httpx
import respx

from scripts.sources.claude_marketplaces import ClaudeMarketplacesSource

# Simulated homepage. The buildId comes from __NEXT_DATA__.
_HOMEPAGE_HTML = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"buildId":"ABC123","props":{}}
</script>
</body></html>
"""

# One category response.
_CATEGORY_JSON_AI_AGENTS = {
    "pageProps": {
        "marketplaces": [
            {"github": "https://github.com/alice/aagent"},
            {"github": "https://github.com/bob/orch"},
        ],
    },
}


@respx.mock
def test_uses_buildid_to_fetch_categories() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text=_HOMEPAGE_HTML)
    )
    # Return data for ai-agents; empty for everything else.
    respx.get(
        "https://claudemarketplaces.com/_next/data/ABC123/marketplaces/category/ai-agents.json"
    ).mock(return_value=httpx.Response(200, json=_CATEGORY_JSON_AI_AGENTS))
    respx.get(
        url__regex=r"https://claudemarketplaces\.com/_next/data/ABC123/marketplaces/category/.+\.json"
    ).mock(return_value=httpx.Response(200, json={"pageProps": {"marketplaces": []}}))

    src = ClaudeMarketplacesSource()
    results = list(src.fetch_candidates())
    assert {c.repo for c in results} == {"alice/aagent", "bob/orch"}
    assert all(c.source == "claude_marketplaces" for c in results)
    assert all(c.hint_assistants == ["claude-code"] for c in results)


@respx.mock
def test_missing_buildid_emits_nothing() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text="<html><body>no script</body></html>")
    )
    src = ClaudeMarketplacesSource()
    assert list(src.fetch_candidates()) == []


@respx.mock
def test_category_404_skipped_others_continue() -> None:
    respx.get("https://claudemarketplaces.com/").mock(
        return_value=httpx.Response(200, text=_HOMEPAGE_HTML)
    )
    respx.get(
        "https://claudemarketplaces.com/_next/data/ABC123/marketplaces/category/ai-agents.json"
    ).mock(return_value=httpx.Response(404))
    respx.get(
        url__regex=r"https://claudemarketplaces\.com/_next/data/ABC123/marketplaces/category/.+\.json"
    ).mock(return_value=httpx.Response(200, json={"pageProps": {
        "marketplaces": [{"github": "https://github.com/x/y"}],
    }}))
    src = ClaudeMarketplacesSource()
    repos = {c.repo for c in src.fetch_candidates()}
    assert repos == {"x/y"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_claude_marketplaces.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/sources/claude_marketplaces.py`**

```python
"""claudemarketplaces.com via Next.js _next/data JSON endpoints.

Strategy: pull buildId from homepage's __NEXT_DATA__ script, then GET the
JSON for each category. The category JSON typically carries a marketplaces
list where each entry has a GitHub URL field."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from scripts.sources.base import RawCandidate

log = logging.getLogger(__name__)

BASE = "https://claudemarketplaces.com"

CATEGORIES: tuple[str, ...] = (
    "ai-agents", "automation", "backend-api", "blockchain-web",
    "business-finance", "communication", "data-analytics", "database",
    "design-creative", "development", "devops-cloud", "documentation",
    "frontend", "git-version-control", "llm-integration", "mcp-servers",
    "media", "memory-context", "mobile", "productivity", "sales-marketing",
    "scientific-research", "security", "testing-quality",
)

_GH_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)",
)
USER_AGENT = "ai-plugin-rankings-bot/1.0"


def _extract_build_id(homepage_html: str) -> str | None:
    soup = BeautifulSoup(homepage_html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        return None
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return None
    build_id = data.get("buildId")
    return build_id if isinstance(build_id, str) else None


class ClaudeMarketplacesSource:
    name = "claude_marketplaces"
    default_assistant = "claude-code"

    def __init__(self, base_url: str = BASE) -> None:
        self._base_url = base_url

    def fetch_candidates(self) -> Iterable[RawCandidate]:
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=30) as c:
            try:
                home = c.get("/")
                home.raise_for_status()
            except httpx.HTTPError:
                log.warning("claudemarketplaces home fetch failed")
                return
            build_id = _extract_build_id(home.text)
            if not build_id:
                log.warning("could not find buildId on claudemarketplaces")
                return

            seen: set[str] = set()
            for cat in CATEGORIES:
                path = f"/_next/data/{build_id}/marketplaces/category/{cat}.json"
                try:
                    resp = c.get(path)
                except httpx.HTTPError:
                    log.warning("category fetch failed: %s", cat)
                    continue
                if not resp.is_success:
                    log.warning("category %s returned %d", cat, resp.status_code)
                    continue
                payload = resp.json()
                marketplaces = payload.get("pageProps", {}).get("marketplaces", [])
                for entry in marketplaces:
                    # The github field shape may vary; accept any string field with a github URL.
                    for value in entry.values():
                        if not isinstance(value, str):
                            continue
                        m = _GH_URL_RE.search(value)
                        if not m:
                            continue
                        owner, name = m.group(1), m.group(2).rstrip(".")
                        repo = f"{owner}/{name}"
                        if repo in seen:
                            continue
                        seen.add(repo)
                        yield RawCandidate(
                            repo=repo, source=self.name,
                            hint_assistants=["claude-code"],
                        )
                        break  # only one repo per entry
```

- [ ] **Step 4: Run tests + gates**

Run: `pytest tests/sources/test_claude_marketplaces.py -v && mypy scripts tests && ruff check .`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/sources/claude_marketplaces.py tests/sources/test_claude_marketplaces.py
git commit -m "Source: claudemarketplaces.com via _next/data JSON"
```

---

## Task 10: Rewrite discover.py — assistant resolution + orchestrator

**Files:**
- Modify: `scripts/discover.py` (full rewrite — delete current content)
- Modify: `tests/test_discover.py` (full rewrite — delete current content)

The v1 `find_candidates` / `Candidate` / `render_candidate_pr_body` API is being replaced. Old tests go too.

- [ ] **Step 1: Delete old discover content and tests**

```bash
rm scripts/discover.py tests/test_discover.py
```

(They will be replaced in step 3.)

- [ ] **Step 2: Write the failing tests**

`tests/test_discover.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from scripts.discover import Addition, resolve_assistants, run_discover
from scripts.github_api import RepoData, RepoMissingError
from scripts.sources.base import RawCandidate


def _repo(repo: str, stars: int, archived: bool = False,
          description: str = "") -> RepoData:
    return RepoData(
        repo=repo, stars=stars, forks=0, open_issues=0,
        archived=archived, pushed_at="2026-05-28T00:00:00Z",
    )


SEED_YAML = """\
# header

plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
"""


def _seed(tmp_path: Path) -> tuple[Path, Path]:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_YAML)
    log = tmp_path / "discovery.log"
    return yaml, log


# --- resolve_assistants ----------------------------------------------------

def test_resolve_assistants_uses_hints() -> None:
    data = _repo("o/x", 1000, description="Some tool")
    out = resolve_assistants(data, {"cursor"}, readme="")
    assert out == {"cursor"}


def test_resolve_assistants_adds_from_readme() -> None:
    data = _repo("o/x", 1000, description="A plugin for Claude Code and OpenAI Codex")
    out = resolve_assistants(data, set(), readme="")
    assert out == {"claude-code", "codex"}


def test_resolve_assistants_cursor_requires_context() -> None:
    """Bare 'cursor' in README (e.g. DB cursor) should NOT tag cursor."""
    data = _repo("o/x", 1000, description="Returns a DB cursor row by row")
    out = resolve_assistants(data, set(), readme="")
    assert "cursor" not in out


def test_resolve_assistants_cursor_with_ide_context() -> None:
    data = _repo("o/x", 1000,
                 description="Cursor editor extension for refactoring")
    out = resolve_assistants(data, set(), readme="")
    assert "cursor" in out


# --- run_discover ----------------------------------------------------------

def test_below_threshold_skipped(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/small", 999,
        description="Claude Code plugin")
    gh.fetch_readme.return_value = "Claude Code plugin"
    source = MagicMock()
    source.name = "test_src"
    source.fetch_candidates.return_value = [RawCandidate(
        repo="o/small", source="test_src", hint_assistants=["claude-code"])]
    run_discover(yaml, log, [source], gh, today="2026-05-29", disabled=set())
    assert "small" not in yaml.read_text()


def test_at_threshold_added(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/big", 1000,
        description="Claude Code plugin")
    gh.fetch_readme.return_value = ""
    source = MagicMock()
    source.name = "test_src"
    source.fetch_candidates.return_value = [RawCandidate(
        repo="o/big", source="test_src", hint_assistants=["claude-code"])]
    run_discover(yaml, log, [source], gh, today="2026-05-29", disabled=set())
    assert "o/big" in yaml.read_text()
    assert "1000 stars" in log.read_text()


def test_archived_skipped(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/dead", 5000, archived=True,
        description="Claude Code plugin")
    gh.fetch_readme.return_value = ""
    source = MagicMock()
    source.name = "test_src"
    source.fetch_candidates.return_value = [RawCandidate(
        repo="o/dead", source="test_src", hint_assistants=["claude-code"])]
    run_discover(yaml, log, [source], gh, today="2026-05-29", disabled=set())
    assert "o/dead" not in yaml.read_text()


def test_already_known_repo_not_refetched(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    source = MagicMock()
    source.name = "test_src"
    source.fetch_candidates.return_value = [RawCandidate(
        repo="obra/superpowers", source="test_src",
        hint_assistants=["claude-code"])]
    run_discover(yaml, log, [source], gh, today="2026-05-29", disabled=set())
    gh.fetch_repo.assert_not_called()


def test_dedupe_across_sources(tmp_path: Path) -> None:
    """Same repo from two sources: one fetch_repo call, hints unioned."""
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/multi", 2000,
        description="Plugin for Claude Code")
    gh.fetch_readme.return_value = ""
    s1 = MagicMock(); s1.name = "src1"
    s1.fetch_candidates.return_value = [RawCandidate(
        repo="o/multi", source="src1", hint_assistants=["claude-code"])]
    s2 = MagicMock(); s2.name = "src2"
    s2.fetch_candidates.return_value = [RawCandidate(
        repo="o/multi", source="src2", hint_assistants=["codex"])]
    additions = run_discover(yaml, log, [s1, s2], gh,
        today="2026-05-29", disabled=set())
    gh.fetch_repo.assert_called_once_with("o/multi")
    assert len(additions) == 1
    via = additions[0].via
    assert set(via) == {"src1", "src2"}


def test_disabled_source_not_called(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    src = MagicMock(); src.name = "naughty"
    run_discover(yaml, log, [src], gh, today="2026-05-29",
                 disabled={"naughty"})
    src.fetch_candidates.assert_not_called()


def test_failing_source_does_not_abort_run(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/ok", 5000,
        description="Claude Code plugin")
    gh.fetch_readme.return_value = ""
    bad = MagicMock(); bad.name = "bad"
    bad.fetch_candidates.side_effect = RuntimeError("boom")
    good = MagicMock(); good.name = "good"
    good.fetch_candidates.return_value = [RawCandidate(
        repo="o/ok", source="good", hint_assistants=["claude-code"])]
    additions = run_discover(yaml, log, [bad, good], gh,
        today="2026-05-29", disabled=set())
    assert len(additions) == 1
    assert additions[0].repo == "o/ok"


def test_missing_repo_skipped(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.side_effect = RepoMissingError("o/gone")
    s = MagicMock(); s.name = "s"
    s.fetch_candidates.return_value = [RawCandidate(
        repo="o/gone", source="s", hint_assistants=["claude-code"])]
    run_discover(yaml, log, [s], gh, today="2026-05-29", disabled=set())
    assert "o/gone" not in yaml.read_text()


def test_no_assistants_resolved_skipped(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/x", 5000, description="Unrelated tool")
    gh.fetch_readme.return_value = "Just a tool"
    s = MagicMock(); s.name = "s"
    # No hint and README/description has no markers
    s.fetch_candidates.return_value = [RawCandidate(
        repo="o/x", source="s", hint_assistants=[])]
    run_discover(yaml, log, [s], gh, today="2026-05-29", disabled=set())
    assert "o/x" not in yaml.read_text()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_discover.py -v`
Expected: FAIL — `scripts.discover` missing (we deleted it).

- [ ] **Step 4: Implement the new `scripts/discover.py`**

```python
"""Multi-source discovery orchestrator.

Aggregates candidates from all configured sources, dedupes by repo, fetches
canonical star counts via the GitHub API, applies the >=1000-star +
non-archived filter, resolves multi-assistant tags by hint + README grep,
generates slug IDs, appends new entries to plugins.yaml (preserving header
comments via ruamel.yaml), writes an audit line to discovery.log, and exits.

Designed for the weekly cron. The workflow itself does the git
add+commit+push after this script returns successfully."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.github_api import GitHubClient, RepoData, RepoMissingError
from scripts.id_gen import generate_id
from scripts.models import PluginEntry
from scripts.plugins_yaml import load_registry
from scripts.sources.awesome_list import AwesomeListSource
from scripts.sources.base import Source
from scripts.sources.claude_marketplaces import ClaudeMarketplacesSource
from scripts.sources.codex_marketplace import CodexMarketplaceSource
from scripts.sources.github_code_search import GithubCodeSearchSource
from scripts.sources.github_topic_search import GithubTopicSearchSource
from scripts.yaml_writer import append_plugins_to_yaml

log = logging.getLogger(__name__)

STAR_THRESHOLD = 1000
KNOWN_ASSISTANTS = {"claude-code", "cursor", "copilot", "codex"}


@dataclass(frozen=True)
class Addition:
    repo: str
    data: RepoData
    assistants: list[str]
    via: list[str]


def resolve_assistants(
    data: RepoData, hints: set[str], readme: str | None,
) -> set[str]:
    out = {h for h in hints if h in KNOWN_ASSISTANTS}
    text = ((data.description or "") + " " + (readme or ""))[:5_000].lower()
    if "claude code" in text or "claude-code" in text:
        out.add("claude-code")
    if "cursor" in text and any(
        k in text for k in ("editor", "ide", "rules", "extension")
    ):
        out.add("cursor")
    if "github copilot" in text or "copilot extension" in text:
        out.add("copilot")
    if "codex cli" in text or "openai codex" in text:
        out.add("codex")
    return out


def _append_log_lines(log_path: Path, lines: list[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def run_discover(
    plugins_yaml: Path,
    discovery_log: Path,
    sources: list[Source],
    gh: GitHubClient,
    today: str,
    disabled: set[str],
) -> list[Addition]:
    registry = load_registry(plugins_yaml)
    known_repos = {p.repo.lower() for p in registry.plugins}

    hints_by_repo: dict[str, set[str]] = {}
    sources_by_repo: dict[str, set[str]] = {}

    for source in sources:
        if source.name in disabled:
            log.info("source %s disabled; skipping", source.name)
            continue
        try:
            for raw in source.fetch_candidates():
                if raw.repo.lower() in known_repos:
                    continue
                hints_by_repo.setdefault(raw.repo, set()).update(raw.hint_assistants)
                sources_by_repo.setdefault(raw.repo, set()).add(raw.source)
        except Exception:
            log.exception("source %s failed; continuing", source.name)

    additions: list[Addition] = []
    for repo in sorted(hints_by_repo.keys()):
        try:
            data = gh.fetch_repo(repo)
        except RepoMissingError:
            continue
        if data.stars < STAR_THRESHOLD or data.archived:
            continue
        try:
            readme = gh.fetch_readme(repo)
        except Exception:
            log.warning("could not fetch README for %s", repo)
            readme = None
        assistants = resolve_assistants(data, hints_by_repo[repo], readme)
        if not assistants:
            log.warning("no assistants resolved for %s; skipping", repo)
            continue
        additions.append(Addition(
            repo=repo, data=data,
            assistants=sorted(assistants),
            via=sorted(sources_by_repo[repo]),
        ))

    if not additions:
        return []

    existing_ids = {p.id for p in registry.plugins}
    new_entries: list[PluginEntry] = []
    log_lines: list[str] = []
    for addition in additions:
        slug = generate_id(addition.repo, existing_ids)
        existing_ids.add(slug)
        new_entries.append(PluginEntry(
            id=slug, repo=addition.repo,
            assistants=addition.assistants, added=today,
        ))
        log_lines.append(
            f"{today}  {addition.repo}  {addition.data.stars} stars  "
            f"via={','.join(addition.via)}  "
            f"assistants={','.join(addition.assistants)}"
        )

    append_plugins_to_yaml(plugins_yaml, new_entries)
    _append_log_lines(discovery_log, log_lines)
    return additions


def main() -> None:
    import sys

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    disabled = {
        s.strip() for s in os.environ.get("DISABLED_SOURCES", "").split(",")
        if s.strip()
    }
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    gh = GitHubClient(token=token)
    sources: list[Source] = [
        GithubCodeSearchSource(token=token),
        GithubTopicSearchSource(token=token),
        AwesomeListSource(token=token),
        ClaudeMarketplacesSource(),
        CodexMarketplaceSource(),
    ]
    try:
        run_discover(
            plugins_yaml=Path("plugins.yaml"),
            discovery_log=Path("discovery.log"),
            sources=sources,
            gh=gh,
            today=today,
            disabled=disabled,
        )
    finally:
        gh.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests + gates**

Run: `pytest tests/test_discover.py -v && mypy scripts tests && ruff check .`
Expected: 13 tests passed, clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/discover.py tests/test_discover.py
git commit -m "Rewrite discover.py: multi-source aggregator with auto-commit"
```

---

## Task 11: Integration test for the full orchestrator

**Files:**
- Create: `tests/test_discover_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/test_discover_integration.py`:

```python
"""End-to-end with stub sources and mocked GitHub API. Verifies the
full chain: sources → dedupe → fetch → filter → assistants → write."""
from pathlib import Path
from unittest.mock import MagicMock

from scripts.discover import run_discover
from scripts.github_api import RepoData
from scripts.plugins_yaml import load_registry
from scripts.sources.base import RawCandidate


SEED_YAML = """\
# Curated registry of AI coding assistant plugins.

plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
"""


def _repo(repo: str, stars: int, desc: str = "Claude Code plugin") -> RepoData:
    return RepoData(
        repo=repo, stars=stars, forks=0, open_issues=0,
        archived=False, pushed_at="2026-05-28T00:00:00Z",
    )


def test_full_orchestrator_with_three_stub_sources(tmp_path: Path) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_YAML)
    log = tmp_path / "discovery.log"

    # 5 candidates, 2 sources each touch one of the same.
    # - o/known (already in plugins.yaml) — should be skipped
    # - o/small — under threshold
    # - o/big1 — qualifies, only one source
    # - o/big2 — qualifies, two sources (dedup, hint union)
    # - o/dead — archived, skipped
    src1 = MagicMock(); src1.name = "src1"
    src1.fetch_candidates.return_value = [
        RawCandidate(repo="obra/superpowers", source="src1",
                     hint_assistants=["claude-code"]),
        RawCandidate(repo="o/small", source="src1",
                     hint_assistants=["claude-code"]),
        RawCandidate(repo="o/big1", source="src1",
                     hint_assistants=["claude-code"]),
        RawCandidate(repo="o/big2", source="src1",
                     hint_assistants=["claude-code"]),
        RawCandidate(repo="o/dead", source="src1",
                     hint_assistants=["claude-code"]),
    ]
    src2 = MagicMock(); src2.name = "src2"
    src2.fetch_candidates.return_value = [
        RawCandidate(repo="o/big2", source="src2",
                     hint_assistants=["codex"]),
    ]

    gh = MagicMock()

    def fetch_repo(repo: str) -> RepoData:
        return {
            "o/small": _repo("o/small", 50),
            "o/big1": _repo("o/big1", 2500),
            "o/big2": _repo("o/big2", 5000),
            "o/dead": RepoData(
                repo="o/dead", stars=8000, forks=0, open_issues=0,
                archived=True, pushed_at="2024-01-01T00:00:00Z",
            ),
        }[repo]
    gh.fetch_repo.side_effect = fetch_repo
    gh.fetch_readme.return_value = ""

    additions = run_discover(yaml, log, [src1, src2], gh,
                             today="2026-05-29", disabled=set())
    # Two additions: big1 + big2
    repos_added = {a.repo for a in additions}
    assert repos_added == {"o/big1", "o/big2"}

    # big2 sourced from both src1 and src2; assistants are unioned
    big2 = next(a for a in additions if a.repo == "o/big2")
    assert set(big2.via) == {"src1", "src2"}
    assert set(big2.assistants) == {"claude-code", "codex"}

    # plugins.yaml now has 3 entries
    reg = load_registry(yaml)
    assert {p.repo for p in reg.plugins} == {
        "obra/superpowers", "o/big1", "o/big2",
    }

    # discovery.log has 2 lines
    log_text = log.read_text().splitlines()
    assert len(log_text) == 2
    assert any("o/big1" in line and "2500 stars" in line for line in log_text)
    assert any("o/big2" in line and "via=src1,src2" in line for line in log_text)

    # plugins.yaml header comment preserved
    assert "# Curated registry" in yaml.read_text()


def test_no_qualifying_candidates_no_writes(tmp_path: Path) -> None:
    """When nothing qualifies, plugins.yaml and discovery.log untouched."""
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_YAML)
    log = tmp_path / "discovery.log"
    before = yaml.read_text()

    src = MagicMock(); src.name = "s"
    src.fetch_candidates.return_value = [RawCandidate(
        repo="o/small", source="s", hint_assistants=["claude-code"])]
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/small", 100)
    gh.fetch_readme.return_value = ""

    additions = run_discover(yaml, log, [src], gh,
        today="2026-05-29", disabled=set())
    assert additions == []
    assert yaml.read_text() == before
    assert not log.exists()
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_discover_integration.py -v`
Expected: 2 passed.

- [ ] **Step 3: Run the full suite to make sure nothing else broke**

Run: `pytest -v && mypy scripts tests && ruff check .`
Expected: all tests pass (55 from v1 + new ones from T2–T11), mypy clean, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_discover_integration.py
git commit -m "Integration test: discover full orchestrator with stub sources"
```

---

## Task 12: Update the discover.yml workflow

**Files:**
- Modify: `.github/workflows/discover.yml`
- Delete: `scripts/run_discover.py`

The old workflow built a PR; the new one auto-commits to main directly.

- [ ] **Step 1: Delete the obsolete entry script**

```bash
rm scripts/run_discover.py
```

- [ ] **Step 2: Replace the workflow file**

Overwrite `.github/workflows/discover.yml` with:

```yaml
name: Weekly discovery

on:
  schedule:
    - cron: "0 5 * * 0"
  workflow_dispatch:
    inputs:
      disabled_sources:
        description: "Comma-separated source names to skip (e.g. claude_marketplaces)"
        required: false
        default: ""

permissions:
  contents: write

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

      - name: Configure git
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

      - name: Run discovery
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DISABLED_SOURCES: ${{ inputs.disabled_sources }}
        run: python -m scripts.discover

      - name: Commit additions
        run: |
          git add plugins.yaml discovery.log
          if git diff --cached --quiet; then
            echo "No new plugins this run."
          else
            # numstat output: "<added> <removed> <path>" per file. discovery.log
            # is append-only, so <added> is the count of new entries.
            COUNT=$(git diff --cached --numstat -- discovery.log | awk '{print $1+0}')
            [ -z "$COUNT" ] && COUNT=0
            git commit -m "Auto-add ${COUNT} plugins from discovery ($(date -u +%Y-%m-%d))"
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
              title: `Weekly discovery failed: ${today}`,
              body: `See: ${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`,
              labels: ['cron-failure'],
            });
```

- [ ] **Step 3: Validate the workflow YAML parses**

Run:
```bash
source .venv/bin/activate
python -c "import yaml; yaml.safe_load(open('.github/workflows/discover.yml'))"
```
Expected: no output (silent success).

- [ ] **Step 4: Run full gates one more time**

Run: `pytest -v && mypy scripts tests && ruff check .`
Expected: all pass, no references to deleted `run_discover` anywhere.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/discover.yml
git rm scripts/run_discover.py
git commit -m "Workflow: discover.yml auto-commits, no more PR step"
```

---

## Task 13: Add `make discover-smoke` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Append the new target**

Edit `Makefile`. Add `discover-smoke` to the `.PHONY` line and add a new target at the bottom:

```makefile
.PHONY: test lint typecheck smoke discover-smoke

# ... existing targets ...

discover-smoke:
	@if [ -z "$$GITHUB_TOKEN" ]; then \
		if command -v gh >/dev/null 2>&1; then \
			GITHUB_TOKEN=$$(gh auth token); export GITHUB_TOKEN; \
		else \
			echo "Set GITHUB_TOKEN or install gh CLI"; exit 1; \
		fi; \
	fi; \
	python -m scripts.discover; \
	echo "Discovery complete. Inspect:"; \
	echo "  plugins.yaml (new entries appended)"; \
	echo "  discovery.log (audit lines appended)"
```

Use real tab indentation under each target.

- [ ] **Step 2: Verify the target parses**

Run: `make -n discover-smoke`
Expected: prints the recipe lines without errors.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "Makefile: discover-smoke target for local discovery dry-run"
```

---

## Task 14: End-to-end local dry run + push

This is the final verification step.

- [ ] **Step 1: Run the full suite**

Run: `source .venv/bin/activate && pytest -v && mypy scripts tests && ruff check .`
Expected: all tests pass, mypy + ruff clean.

- [ ] **Step 2: Local smoke against real APIs (optional but recommended)**

If `gh` is logged in:
```bash
make discover-smoke
```

Inspect:
- `plugins.yaml` — new entries appended (or no change if none qualify)
- `discovery.log` — audit lines for any additions
- Header comment block of `plugins.yaml` still present

If you don't want the smoke results committed (e.g. exploring), revert with `git checkout -- plugins.yaml; rm -f discovery.log`.

- [ ] **Step 3: Push to GitHub**

```bash
git push origin main
```

The next scheduled run (Sundays 05:00 UTC) will use the new pipeline automatically. You can also trigger one immediately via:

```bash
gh workflow run "Weekly discovery"
```

- [ ] **Step 4: Final commit (none required)**

This task is verification + handoff; nothing to commit unless the smoke test added entries you want to keep.

---

## Self-Review

Cross-checked the plan against the spec:

| Spec section | Implementing task(s) |
|---|---|
| Source protocol & RawCandidate | T2 |
| GitHub code search source | T5 |
| GitHub topic + name search source | T6 |
| Awesome-list source | T7 |
| Codex marketplace source | T8 |
| Claude marketplaces source (Next.js _next/data) | T9 |
| Orchestrator: dedupe + fetch + threshold + write | T10, T11 |
| Assistant resolution function | T10 |
| ID generation with collision handling | T3 |
| YAML write that preserves comments (`ruamel.yaml`) | T4 |
| `discovery.log` audit format | T10, T11 |
| `DISABLED_SOURCES` env-var kill-switch | T10, T12 |
| Per-source try/except isolation | T10 |
| Workflow: direct commit, no PR | T12 |
| Delete `run_discover.py` | T12 |
| `make discover-smoke` | T13 |
| Test pyramid (unit per source + orchestrator + integration) | T5–T11 |

No placeholders, no "TBD"s. Each task has runnable code in every step.

Type / signature consistency:
- `RawCandidate` defined in T2 is consumed identically in T5–T9, T10, T11
- `Source` protocol's `name`, `fetch_candidates() -> Iterable[RawCandidate]` matches every adapter's class
- `generate_id` signature `(repo, existing_ids) -> str` in T3 matches T10 usage
- `append_plugins_to_yaml(path, list[PluginEntry])` in T4 matches T10 usage
- `Addition` dataclass in T10 carries `repo, data, assistants, via` consistently
- `resolve_assistants(data, hints, readme)` signature in T10 matches its test in step 2

One requirement worth flagging here that the spec touches lightly: the **discover.log file already exists from previous runs**. The orchestrator appends; it doesn't truncate. T10 step 3 implements that (open with mode `"a"`). The workflow `git add discovery.log` covers the case where it didn't exist before (first run creates it).

---

## Notes for the executor

- **TDD discipline**: every implementation step is preceded by a failing test. If a test mysteriously passes before implementation, the test is wrong — investigate.
- **No live API tests in CI**: T14 is the only step that may hit real APIs (locally). Don't add a CI step that does.
- **The orchestrator deletes-and-rewrites** the old `discover.py` and `tests/test_discover.py`. The v1 `Candidate`, `find_candidates`, `render_candidate_pr_body`, and topic-only flow are gone. Do not preserve them.
- **`ruamel.yaml` formatting** may render `assistants: [claude-code]` as a block list (`- claude-code`) instead of inline-flow. That's still valid YAML and the loader accepts both. Don't bend over backwards to preserve inline format.
- **First production run may be slow** (5 sources × hundreds of candidates each, then a star fetch per unique repo). Within the GitHub rate limit but expect 5–15 minutes wall clock. The workflow's default 6-hour timeout is plenty.
