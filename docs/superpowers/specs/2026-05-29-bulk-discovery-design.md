# Bulk Discovery — Design

**Date:** 2026-05-29
**Status:** Design approved, pending implementation plan
**Builds on:** `2026-05-28-ai-plugin-rankings-design.md`

## Problem

The v1 discovery workflow uses four GitHub topic queries and opens a candidate PR for humans to review. That returned only ~22 candidates on first run — far short of the actual AI assistant plugin universe. The user wants the registry to grow autonomously from many sources, automatically capturing every credible plugin (≥1000 stars) so the rankings become a real directory rather than a hand-curated snapshot.

## Goal

Replace the v1 discovery workflow with a multi-source ingestion pipeline that:

1. Queries five independent sources for plugin candidates.
2. Fetches canonical star counts from the GitHub API (one call per unique repo).
3. Auto-appends every repo with ≥1000 stars to `plugins.yaml` and commits directly to `main`.
4. Records every addition in an append-only `discovery.log` audit file.

Below-threshold candidates are silently dropped. No PRs are opened; no candidate review step.

## Scope

**In scope:**

- Five source adapters (GitHub code search, expanded topic/name search, awesome-list parsing, claudemarketplaces.com, codex-marketplace.com).
- One orchestrator that dedupes, fetches stars, applies the ≥1000 filter, and writes additions.
- Per-source kill-switch via env var.
- Multi-target assistant detection from repo description + README grep.
- ID slug generation with deterministic collision handling.
- YAML write that preserves the top-of-file comment block.
- Unit tests per source + orchestrator integration test.

**Out of scope:**

- Candidate-PR flow (replaced — gone).
- LLM enrichment (still disabled; unrelated).
- Removing entries (still manual via PR).
- Per-source quality scoring beyond stars + archived.
- Pagination beyond first 100 results per query.
- Auto-tagging of plugin categories (those come from enrichment, when re-enabled).

## Architecture

```
                  ┌──────────────┐
                  │  Workflow    │  weekly cron: discover.yml
                  └───────┬──────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  scripts/discover.py  │  orchestrator
              │  (rewritten)          │
              └─────────┬─────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
  sources/         sources/         sources/        sources/        sources/
  github_code_     github_topic_    awesome_        claude_         codex_
  search.py        search.py        list.py         marketplaces.py marketplace.py
        │               │               │               │               │
        └───────────────┴───────────────┴───────────────┴───────────────┘
                                  │
                                  ▼
              dedupe by repo, union hint_assistants
                                  │
                                  ▼
                       github_api.fetch_repo()    (canonical star check)
                                  │
                                  ▼
                       filter: stars≥1000 ∧ ¬archived
                                  │
                                  ▼
                  resolve_assistants(data, hints)  (README grep)
                                  │
                                  ▼
                  generate slug id (collision-handled)
                                  │
                                  ▼
                  append to plugins.yaml (ruamel.yaml, preserves comments)
                                  │
                                  ▼
                  append line to discovery.log
                                  │
                                  ▼
                  git commit + push origin main
```

## Source Adapters

### Common interface

```python
class Source(Protocol):
    name: str
    default_assistant: str

    def fetch_candidates(self) -> Iterable[RawCandidate]: ...


@dataclass(frozen=True)
class RawCandidate:
    repo: str               # "owner/name"
    source: str             # adapter name (e.g. "github_code_search")
    hint_assistants: list[str]
```

Sources emit only `repo + source + hint`. They MUST NOT report star counts (those come from the canonical GitHub fetch in the orchestrator) — multiple sources finding the same repo de-dupe to a single star fetch.

### `github_code_search.py`

Queries GitHub's code search for plugin manifest filenames. One query per filename pattern. Each match's `repository.full_name` becomes a `RawCandidate`.

| Query | Hint |
|---|---|
| `filename:.claude-plugin.json` | claude-code |
| `filename:claude-plugin.json` | claude-code |
| `filename:.cursorrules` | cursor |
| `filename:cursor.json path:.cursor` | cursor |
| `filename:codex-plugin.toml` | codex |
| `filename:codex.toml` | codex |
| `filename:copilot-extension.json` | copilot |

Code search rate limit: 30 req/min. Seven queries fits trivially. Auth: `GITHUB_TOKEN` from Actions.

### `github_topic_search.py`

Subsumes the v1 topic query logic, with an expanded set:

| Query | Hint |
|---|---|
| `topic:claude-code-plugin` | claude-code |
| `topic:claude-skills` | claude-code |
| `topic:claude-code` | claude-code |
| `topic:cursor-rules` | cursor |
| `topic:cursor-extension` | cursor |
| `topic:cursorrules` | cursor |
| `topic:copilot-extension` | copilot |
| `topic:github-copilot-extension` | copilot |
| `topic:codex-plugin` | codex |
| `topic:codex-extension` | codex |
| `topic:mcp-server` | claude-code |
| `in:name claude-code stars:>10` | claude-code |
| `in:name cursor-rules stars:>10` | cursor |

GitHub Search/Repositories endpoint (5,000/hr). Caps at 100 results per query.

### `awesome_list.py`

Fetches the README of each known awesome-* list, regexes out every `https://github.com/<owner>/<name>` URL, emits each as a `RawCandidate`. Awesome-list itself is excluded.

Seed:

```python
AWESOME_LISTS: list[tuple[str, str]] = [
    ("ComposioHQ/awesome-claude-plugins", "claude-code"),
    ("ccplugins/awesome-claude-code-plugins", "claude-code"),
    ("quemsah/awesome-claude-plugins", "claude-code"),
]
```

Adding more lists is a one-line PR. The list-to-hint mapping carries the source's editorial bias forward, but the orchestrator's README-grep step refines per-repo.

### `claude_marketplaces.py`

Targets claudemarketplaces.com. The site is server-rendered with Next.js. Strategy:

1. GET the homepage; extract `__NEXT_DATA__` script content; pull `buildId`.
2. For each of 21 marketplace category slugs, GET `/_next/data/{buildId}/marketplaces/category/{slug}.json`.
3. Parse the embedded marketplace list; each entry yields a GitHub `repo`.

Hint: `claude-code` (the site is Claude-focused).

If `buildId` extraction fails OR a category JSON returns 404 → source logs warning, emits empty list, orchestrator continues. This is the most fragile source; the kill-switch exists primarily for it.

### `codex_marketplace.py`

Targets codex-marketplace.com/plugins. The page renders enough plugin data in static HTML that the v1 prototype WebFetch returned 50 entries. Parse with BeautifulSoup, extract every `<a href="https://github.com/...">`, emit as `RawCandidate`.

Hint per entry: `codex` by default. Heuristic override: if the repo name contains `"claude"` → also hint `claude-code`.

## Orchestrator

`scripts/discover.py` (rewritten):

```
1. Load plugins.yaml; build known_repos set (lowercased)
2. disabled = parse_env("DISABLED_SOURCES")  # comma-separated
3. hints_by_repo: dict[str, set[str]] = {}       # repo → unioned hint_assistants
   sources_by_repo: dict[str, set[str]] = {}     # repo → set of source names that found it
4. For each enabled source:
     try:
         for raw in source.fetch_candidates():
             if raw.repo.lower() in known_repos: continue
             hints_by_repo.setdefault(raw.repo, set()).update(raw.hint_assistants)
             sources_by_repo.setdefault(raw.repo, set()).add(raw.source)
     except Exception:
         log.exception("source %s failed; continuing", source.name)
5. For each repo sorted by name:
     try: data = gh.fetch_repo(repo)
     except RepoMissingError: continue
     # RateLimitError bubbles → aborts whole run
     if data.stars < 1000 or data.archived: continue
     assistants = resolve_assistants(data, hints_by_repo[repo], gh)
     additions.append(Addition(
         repo=repo, data=data,
         assistants=sorted(assistants),
         via=sorted(sources_by_repo[repo]),
     ))
6. If additions is non-empty:
     for addition in additions:
         slug = generate_id(addition.repo, existing_ids=registry_ids | new_slugs)
         append PluginEntry to in-memory registry
         append line to discovery.log
     write_yaml_with_comment_preservation(plugins.yaml, registry)
     append discovery.log
     git add plugins.yaml discovery.log
     git commit -m "Auto-add N plugins from discovery (YYYY-MM-DD)"
     git push origin main
```

## Assistant Resolution

```python
def resolve_assistants(
    data: RepoData, hints: set[str], gh: GitHubClient,
) -> set[str]:
    """Start with source hints; add any assistant whose marker appears in
    description + first 5KB of README."""
    out = set(hints)
    readme = (gh.fetch_readme(data.repo) or "")[:5_000]
    blob = (data.description or "") + " " + readme
    blob_lower = blob.lower()
    if "claude code" in blob_lower or "claude-code" in blob_lower:
        out.add("claude-code")
    if "cursor" in blob_lower and (
        "editor" in blob_lower or "ide" in blob_lower or "rules" in blob_lower
    ):
        out.add("cursor")
    if "github copilot" in blob_lower or "copilot extension" in blob_lower:
        out.add("copilot")
    if "codex cli" in blob_lower or "openai codex" in blob_lower:
        out.add("codex")
    return out
```

Cursor needs a context-narrowing AND-clause because "cursor" the SQL/iterator term appears in countless unrelated READMEs.

## ID Generation

```python
def generate_id(repo: str, existing_ids: set[str]) -> str:
    owner, name = repo.split("/")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if slug not in existing_ids:
        return slug
    qualified = f"{owner.lower()}-{slug}"
    if qualified not in existing_ids:
        return qualified
    suffix = hashlib.sha1(repo.encode()).hexdigest()[:4]
    return f"{qualified}-{suffix}"
```

Deterministic: same repo always yields the same id, even across runs.

## YAML Write

Use `ruamel.yaml` (added to `pyproject.toml` deps) instead of `PyYAML` for the orchestrator's write path. `PyYAML` strips comments; `ruamel.yaml` round-trips them. Read existing file → append new entries to the `plugins` list → write back with comments intact.

The existing `scripts/plugins_yaml.py` loader still uses `PyYAML` for validation (it only reads, doesn't write — the comment loss is irrelevant for the load path).

## `discovery.log`

Plain text, append-only. One line per auto-add:

```
2026-05-29  thedotmack/claude-mem  79367 stars  via=github_topic_search,awesome_list  assistants=claude-code,codex,copilot
```

Committed alongside `plugins.yaml` in the same commit. This is the only audit trail of which source surfaced which entry — useful for tuning sources later.

## Kill-Switch

```yaml
# .github/workflows/discover.yml
env:
  DISABLED_SOURCES: ""   # comma-separated, e.g. "claude_marketplaces,awesome_list"
```

Orchestrator skips disabled sources before running them. No code change needed when a source breaks.

## Error Handling

| Failure | Behavior |
|---|---|
| Source raises during `fetch_candidates` | Log traceback, continue with other sources |
| Code/topic search returns 422 (bad query) | Log warning, source emits empty list |
| GitHub repo 404 during orchestrator star fetch | Skip silently |
| GitHub 403 rate limit | Abort run, commit nothing, exit non-zero (existing `RateLimitError` semantics) |
| claudemarketplaces.com buildId not found | Source emits empty list, logs warning, orchestrator continues |
| codex-marketplace.com HTML structure changed | Source emits empty list, logs warning |
| `plugins.yaml` malformed when re-read for write | Abort run, log error, no commit (existing pydantic validation) |
| `git push` rejected | Abort run, log error |

## Testing

**Per source (unit, `respx` for HTTP):**

- `tests/sources/test_github_code_search.py` — given fixture search response, emits expected `RawCandidate` list; empty/malformed response → empty list
- `tests/sources/test_github_topic_search.py` — same shape
- `tests/sources/test_awesome_list.py` — given fixture README, regex extracts every GitHub URL; awesome-list itself excluded; non-github URLs ignored
- `tests/sources/test_claude_marketplaces.py` — given fixture homepage + category JSON, extracts repos; missing buildId → empty list, warning logged
- `tests/sources/test_codex_marketplace.py` — given fixture HTML, BeautifulSoup parses out github links; heuristic claude-name → multi-hint

**Orchestrator (unit):**

- `test_discover_dedupes` — two sources surface same repo, only one star-fetch, hints unioned
- `test_discover_threshold` — repo at 999 stars skipped, 1000 added, 1001 added
- `test_discover_archived_skipped` — archived repo skipped even at 1M stars
- `test_discover_unknown_repos_only` — already-known repos filtered before star fetch (no wasted API calls)
- `test_discover_disabled_source` — `DISABLED_SOURCES=foo` env var skips that source
- `test_discover_one_source_failing` — other sources continue when one raises
- `test_discover_id_collision` — three repos that would slug to the same id all get unique ids
- `test_discover_yaml_write_preserves_comments` — header comment block intact after write

**Integration:**

- `test_discover_e2e` — 3 stub sources + mocked GitHub + temp `plugins.yaml` + temp `discovery.log`. Assert: yaml updated, log appended, slugs deterministic, commit message format correct.

**No live API tests in CI.** Local `make discover-smoke` target runs all five real sources once and prints the would-be additions without committing.

## Open Questions

- **Cursor and Copilot coverage:** the chosen sources lean Claude/Codex. After first real run, expect Cursor and Copilot bins to stay small. Mitigation is more `topic:` / `in:name` queries in `github_topic_search.py` and more entries in `AWESOME_LISTS`; both are PR-able post-launch.
- **claudemarketplaces.com `buildId` stability:** if their Next.js build invalidates frequently, the scraper will need a homepage refetch on every run (already designed for that). If they switch to fully dynamic SSR with no `_next/data`, the kill-switch triggers and that source contributes nothing until reworked.

## Future (out of scope here)

- Programmatic Cursor / Copilot directory integrations (when official APIs surface).
- Per-source observability (success counts, last-success timestamp) emitted to a dashboard.
- Auto-removal of stale plugins (currently still manual via PR).
