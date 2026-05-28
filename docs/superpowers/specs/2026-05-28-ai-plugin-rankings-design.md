# AI Plugin Rankings — Design

**Date:** 2026-05-28
**Status:** Design approved, pending implementation plan

## Problem

There is no equivalent of `EvanLi/Github-Ranking` for AI coding assistant plugins. Users discovering plugins for Claude Code, Cursor, GitHub Copilot, and the OpenAI Codex CLI have no canonical place to see which plugins exist, which are popular, and which are gaining traction right now.

## Goal

A single git repository that publishes two daily-updated rankings of AI assistant plugins:

1. **All-time** — sorted by total GitHub stars.
2. **Trending** — sorted by stars gained in the last 24 hours.

Rankings are broken out per assistant (Claude Code / Cursor / Copilot / Codex CLI) and combined. Each plugin entry shows a one-line LLM-generated description and a category tag. A future website (out of scope for this spec) will consume the same data files.

## Scope

**In scope (v1):**
- Tracking plugins / extensions proper for Claude Code, Cursor, GitHub Copilot, and Codex CLI
- Daily star-count snapshots with 24h and 7d deltas
- LLM-generated description + category metadata (refreshed weekly)
- Curated `plugins.yaml` as source of truth, PR-editable
- Auto-discovery via GitHub Search, surfaced as candidate PRs (never auto-merged)
- Generated `README.md` and per-assistant ranking files

**Out of scope (v1):**
- Skill packs, rule packs, prompt packs, MCP servers, standalone CLI agents (Aider, Cline, etc.)
- Adjacent ecosystems (Windsurf, Continue, Zed AI)
- A website / API
- Real-time updates (daily is fine)
- Per-user features (favorites, alerts)

## Architecture

GitHub Actions runs three scheduled workflows against a single repo. Code, curated registry, and rendered output live on `main`. Historical snapshots live on an orphan `data` branch.

```
┌─────────────────────────────────────────────────────────────┐
│ main branch                                                 │
│                                                             │
│  plugins.yaml ──┐                                           │
│                 ├─> scripts/scrape.py ──> data/latest.json  │
│  GitHub API ────┘                                           │
│                                                             │
│  data/latest.json ──> scripts/render.py ──> README.md       │
│  data/metadata.json                         rankings/*.md   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ (push snapshot)
┌─────────────────────────────────────────────────────────────┐
│ data branch (orphan)                                        │
│  snapshots/2026-05-28.jsonl                                 │
│  snapshots/2026-05-27.jsonl                                 │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

Stack: Python 3.12, `httpx` (HTTP), `pydantic` (schemas), `PyYAML` (registry), `anthropic` SDK (enrichment), `pytest` + `respx` (tests), `ruff` + `mypy --strict` (gates).

## Repo Layout

**`main` branch:**

```
ai-plugin-rankings/
├── README.md                      # Generated: combined top-N + per-assistant index
├── plugins.yaml                   # Curated registry (PR-editable, source of truth)
├── rankings/                      # Generated per-view files
│   ├── all.md                     # All plugins, sorted by stars
│   ├── trending.md                # All plugins, sorted by 24h delta
│   ├── claude-code.md             # Per-assistant: trending + all-time sections
│   ├── cursor.md
│   ├── copilot.md
│   └── codex.md
├── data/
│   ├── latest.json                # Current snapshot used to render
│   └── metadata.json              # LLM-generated descriptions/tags
├── scripts/                       # Pipeline (Python)
│   ├── scrape.py
│   ├── discover.py
│   ├── enrich.py
│   ├── rank.py
│   └── render.py
├── tests/
├── pyproject.toml
└── .github/workflows/
    ├── daily.yml
    ├── weekly-enrich.yml
    └── discover.yml
```

**`data` orphan branch:**

```
snapshots/
├── 2026-05-28.jsonl
├── 2026-05-27.jsonl
└── ...
README.md                          # Explains the data format
```

The branch is orphan (no shared history with `main`) so cloning `main` doesn't pull years of history. The website (future) reads from this branch via raw GitHub URLs or a shallow clone.

## Data Model

### `plugins.yaml` — curated registry

```yaml
plugins:
  - id: superpowers                # Stable slug, never changes
    repo: obra/superpowers         # GitHub owner/name
    assistants: [claude-code]      # One or more of: claude-code, cursor, copilot, codex
    added: 2026-05-28              # Date added to registry

  - id: example-multi-target
    repo: org/multi
    assistants: [cursor, copilot]  # A plugin can target multiple
    added: 2026-05-28
```

Deliberately thin so PRs are trivial to review. Descriptions, tags, and stars are derived elsewhere.

### `data/metadata.json` — LLM-generated, refreshed weekly

```json
{
  "superpowers": {
    "description": "Skill and workflow framework for Claude Code with TDD, debugging, brainstorming",
    "tags": ["workflow", "skills", "tdd"],
    "category": "productivity",
    "enriched_at": "2026-05-25T03:00:00Z",
    "readme_sha": "abc123..."
  }
}
```

`category` is drawn from a fixed enum (the LLM picks from the list, doesn't invent new categories):
`productivity`, `testing`, `debugging`, `code-review`, `documentation`, `language-support`, `mcp-bridge`, `other`.

`readme_sha` lets the weekly job skip enrichment when the README hasn't changed → near-zero LLM cost most weeks.

### `data/latest.json` — current snapshot, rendered each day

```json
{
  "generated_at": "2026-05-28T03:00:00Z",
  "plugins": [
    {
      "id": "superpowers",
      "repo": "obra/superpowers",
      "assistants": ["claude-code"],
      "stars": 1247,
      "stars_24h": 18,
      "stars_7d": 92,
      "previous_stars": 1229,
      "archived": false,
      "status": "ok",
      "url": "https://github.com/obra/superpowers"
    }
  ]
}
```

`status` is one of `ok` | `missing` (repo 404'd) | `archived`. Missing plugins remain visible in rankings with a marker until manually removed via PR.

### Snapshot file (`data` branch, `snapshots/YYYY-MM-DD.jsonl`)

One line per plugin:

```json
{"id":"superpowers","repo":"obra/superpowers","stars":1247,"forks":89,"open_issues":12,"archived":false,"pushed_at":"2026-05-27T18:22:00Z"}
```

JSONL because it streams, greps, and gzips well. Re-running the same day overwrites that day's file (idempotent).

## Pipeline

### Daily job (`daily.yml`) — 03:00 UTC

```
1. Checkout main; checkout data branch into sibling dir
2. Read plugins.yaml
3. For each plugin: GET /repos/{owner}/{name} (GitHub API)
     - Collect: stars, forks, open_issues, archived, pushed_at
     - Retry 5xx with exponential backoff (max 3); 404 → mark "missing"
4. Read yesterday's snapshot from data branch for 24h delta
   Read 7-day-old snapshot if present for 7d delta
5. Write today's snapshot: data branch, snapshots/YYYY-MM-DD.jsonl
6. Merge with data/metadata.json (descriptions from weekly job)
7. Write data/latest.json
8. Render README.md and rankings/*.md from latest.json (deterministic)
9. Commit:
     - data branch: today's snapshot
     - main: latest.json + README + rankings/
10. On unrecoverable error (rate limit or 5xx after retries): exit non-zero, open issue, commit nothing on either branch
```

**Failure mode:** on unrecoverable error (rate limit / persistent 5xx after retries), the run aborts before step 5 and neither branch sees a commit. Either both branches advance together (success) or neither does (failure) — this keeps `data` snapshots and `latest.json` mutually consistent.

A daily commit on `main` is expected and intentional (matches the EvanLi pattern). The README always carries a fresh `generated_at` timestamp.

**Auth:** `GITHUB_TOKEN` (5,000 req/hr) covers thousands of plugins comfortably. ETag/conditional requests deferred until needed.

### Weekly enrichment (`weekly-enrich.yml`) — Sundays 04:00 UTC

```
1. For each plugin in plugins.yaml:
     - GET README via GitHub Contents API
     - sha256(README) → readme_sha
     - If readme_sha matches metadata.json's stored value → skip
     - Else call Anthropic API with prompt:
         "Given this README, output JSON: {description, category, tags}"
         (category from fixed enum; tags from controlled list of ~30)
     - Validate response against pydantic schema; on failure keep previous entry
2. Commit metadata.json to main if changed
```

Skip-if-unchanged is the cost lever. Most weeks ≤10% of plugins have README changes → tiny LLM bill (~cents/week).

### Weekly discovery (`discover.yml`) — Sundays 05:00 UTC

```
1. Query GitHub Search across:
     - topic:claude-code-plugin, topic:cursor-extension, topic:copilot-extension, topic:codex-plugin
     - in:name patterns: "claude-code-*", "cursor-*-extension", "copilot-*", etc.
2. Filter out:
     - Repos already in plugins.yaml
     - <10 stars
     - Archived
     - Last push >1 year ago
3. Open a PR titled "Discovered candidates: YYYY-MM-DD"
     - Body lists each candidate with stars + repo description + guessed assistant
     - Human reviewer accepts (moves entry into plugins.yaml) or closes
4. If nothing new: skip (no empty PR)
```

**Invariant:** discovery never auto-adds to `plugins.yaml`. Every entry passes human review.

## Rendered Output

### `README.md` (top of repo)

```markdown
# AI Coding Assistant Plugin Rankings

Updated daily. Source data in `data/`, history in `data` branch.

## Top 20 trending (24h)
[table of top 20 by stars_24h]

## Top 20 all-time (stars)
[table of top 20 by stars]

## By assistant
- [Claude Code](rankings/claude-code.md) — N plugins
- [Cursor](rankings/cursor.md) — N plugins
- [GitHub Copilot](rankings/copilot.md) — N plugins
- [Codex CLI](rankings/codex.md) — N plugins

## Submit a plugin
Open a PR adding an entry to `plugins.yaml`.
```

### Table columns (everywhere)

| Rank | Plugin | Description | Assistants | Stars | 24h | 7d | Category |

### `rankings/<assistant>.md`

Two sections — "Trending (24h)" then "All-time" — filtered to plugins where that assistant is in the `assistants` list.

Plugins targeting multiple assistants appear in each assistant's file. By design: a reader browsing `cursor.md` should see every plugin that works with Cursor.

### `rankings/all.md` / `rankings/trending.md`

Global lists, one view each, no filtering.

### Determinism

`scripts/render.py` produces byte-identical output for identical `latest.json` input. Tested with golden files in `tests/golden/`. This is what makes the integration test reliable: same fixtures in, same bytes out, no flakiness from sort instability or dict ordering.

## Error Handling

| Failure | Behavior |
|---|---|
| GitHub 404 on plugin | Mark `status: missing`, render with marker, open issue tagged `stale-plugin` |
| GitHub 403 (rate limit) | Retry with backoff once; if still failing, abort run, exit non-zero, commit nothing to main |
| GitHub 5xx | Exp. backoff up to 3 retries; then abort like rate limit |
| Repo archived | Tag `archived` in output (struck-through, sorted to bottom). Star count still tracked |
| Anthropic API down (weekly) | Daily job unaffected; weekly retries next week |
| LLM returns bad JSON | Pydantic validation rejects; keep previous entry; log; don't corrupt file |
| Discovery query fails | Best effort; log, exit 0, no PR that week |
| Any workflow fails | Tiny `github-script` step opens a GitHub Issue so maintainers see a red flag |

**Critical invariant:** no partial state is ever committed to `main`. A run either fully succeeds and commits, or fails and commits nothing. This keeps the `data` branch history and `latest.json` mutually consistent for future graphing.

## Testing

**Unit (pytest):**
- `test_rank.py` — ranking order; ties broken by total stars; archived sorts to bottom
- `test_render.py` — byte-equality vs golden files (determinism)
- `test_delta.py` — 24h / 7d delta math; missing previous snapshot → `null` not `0`; new plugin (no history) → delta equals stars
- `test_schema.py` — pydantic validation of `plugins.yaml` and `metadata.json`; bad fixtures fail loudly
- `test_enrich.py` — canned LLM response updates metadata correctly; bad JSON rejected without corruption

**Integration (one, with `respx` mocking HTTP):**
- Full pipeline run against a 3-plugin fixture `plugins.yaml`, mocked GitHub + Anthropic responses
- Assert: snapshot written, `latest.json` correct, README matches golden file

**No live API tests in CI.** A `make smoke` target lets a maintainer run against real APIs locally before releasing.

**Gates on every PR:** `pytest`, `ruff`, `mypy --strict scripts/`. The daily cron runs on `main` only after gates have passed.

## Open Questions

- **Exact category enum** — the seed list (`productivity`, `testing`, …) is reasonable but can be refined once we see real plugins. Lock in v1 before first enrichment run; expanding the enum later requires a migration step (re-enrich everything).
- **Tag controlled vocabulary** — ~30 tags total, derived from the seed plugins. Same story as categories.
- **Discovery query set** — initial queries are educated guesses. Expect to iterate weekly during early operation as we see which queries find signal vs noise.

## Future (explicitly out of scope here)

- Static website (Next.js or Astro) reading from raw GitHub URLs against `data` branch — graphs, search, filtering
- Open community submissions via lower-friction form (not just PR)
- Adjacent ecosystems (Windsurf, Continue, Zed AI)
- API endpoint
