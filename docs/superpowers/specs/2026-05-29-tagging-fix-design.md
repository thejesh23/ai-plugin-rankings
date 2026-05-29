# Tagging Algorithm Fix + Auto-Render After Discovery

**Date:** 2026-05-29
**Status:** Design approved, pending implementation plan
**Builds on:** `2026-05-29-bulk-discovery-design.md`

## Problem

The Sunday discovery run added 354 plugins to `plugins.yaml` but two algorithm gaps left the live site looking wrong to users:

1. **Mistagging.** `Lum1104/Understand-Anything` (43,865 ★) declares itself as supporting Claude Code, Codex, Cursor, Copilot, and Gemini CLI in its repo description. Our `resolve_assistants` only tagged it `[claude-code]` because:
   - `"codex"` detection required `"codex cli"` or `"openai codex"` (literal compounds)
   - `"copilot"` detection required `"github copilot"` or `"copilot extension"`
   - `"cursor"` detection required co-occurrence with `editor / ide / rules / extension`

   Bare-name mentions in descriptions like `"Works with Claude Code, Codex, Cursor, Copilot"` failed all three patterns and silently dropped three legitimate assistant tags per plugin.

2. **Rendering lag.** Discovery commits to `plugins.yaml` directly but does not re-render `README.md` or `rankings/*.md`. Those files only refresh when the daily cron fires at 03:00 UTC. A user opening the repo right after a Sunday discovery sees the *old* rankings without any of the new entries.

## Goal

1. Replace `resolve_assistants` with a description-only matcher that catches bare assistant names while still suppressing the DB-cursor false-positive case.
2. Have the discovery workflow re-render README and rankings inline after auto-add, so users see the new entries within minutes instead of hours.
3. Provide a one-off `scripts/retag.py` CLI to re-evaluate existing entries against the new logic. Not wired into any cron.

## Scope

**In scope:**
- Rewrite `scripts.discover.resolve_assistants` with looser matchers + Cursor context narrowing.
- Add render-after-discovery steps to `.github/workflows/discover.yml`.
- New `scripts/retag.py` CLI for manual one-off re-evaluation.
- Five new unit tests in `tests/test_discover.py` for the new matcher.
- One unit test in a new `tests/test_retag.py` for the retag flow.

**Out of scope:**
- Re-introducing per-candidate README fetch (we deliberately skip it to stay inside the GitHub rate budget).
- Multi-language description handling (we lowercase + ASCII-match; non-English mentions of "Claude Code" still work, others may miss).
- Tagging quality categories or per-category enrichment (still requires the Anthropic key, still disabled).
- Auto-running retag on a schedule.

## Architecture

No new modules beyond `scripts/retag.py`. Changes are localized to:

```
scripts/
├── discover.py           # resolve_assistants gets rewritten
└── retag.py              # NEW: one-off CLI

tests/
├── test_discover.py      # 5 new tests for resolve_assistants
└── test_retag.py         # NEW: 1 test for retag_all

.github/workflows/
└── discover.yml          # add 3 steps after "Commit additions"
```

## `resolve_assistants` Rewrite

```python
import re

KNOWN_ASSISTANTS = {"claude-code", "cursor", "copilot", "codex"}

# Phrases that suggest a real plugin context (list intros AND product-type
# nouns). Includes "extension/editor/ide/rules" so Cursor descriptions like
# "Cursor editor extension" still match. Excludes bare "for" to avoid false
# positives like "cursor for the database".
_LIST_INTRO_RE = re.compile(
    r"\b(?:works?\s+with|supports?|compatible\s+with|plugin\s+for|"
    r"plugins?\s+for|integrates?\s+with|plugin|extension|editor|ide|rules)\b",
    re.IGNORECASE,
)

# Any of the four assistant names — used for Cursor co-occurrence check.
_OTHER_ASSISTANT_RE = re.compile(
    r"\b(?:claude(?:\s+code|-code)?|copilot|codex)\b",
    re.IGNORECASE,
)


def resolve_assistants(
    data: RepoData, hints: set[str], readme: str | None = None,
) -> set[str]:
    """Determine which assistants a plugin targets.

    Operates on description only. README is ignored (orchestrator never
    fetches it — see bulk-discovery design for the rate-limit rationale)."""
    out = {h for h in hints if h in KNOWN_ASSISTANTS}
    text = (data.description or "").lower()

    if "claude code" in text or "claude-code" in text:
        out.add("claude-code")
    if "copilot" in text:
        out.add("copilot")
    if "codex" in text:
        out.add("codex")

    # Cursor: bare match is too ambiguous (DB cursors, mouse cursors, etc.).
    # Tag only if "cursor" appears inside an 80-char window that ALSO
    # contains either a list-intro phrase or another assistant name.
    for m in re.finditer(r"\bcursor\b", text):
        window = text[max(0, m.start() - 80): m.end() + 80]
        if _LIST_INTRO_RE.search(window) or _OTHER_ASSISTANT_RE.search(window):
            out.add("cursor")
            break

    return out
```

**Why each rule:**

| Marker | Rule | Reasoning |
|---|---|---|
| Claude Code | bare match on `"claude code"` or `"claude-code"` | Distinctive enough that no further narrowing is needed. We deliberately do NOT match bare `"claude"` — it would over-tag descriptions like "Claude Monet" or "Claude Shannon" |
| Copilot | bare match on `"copilot"` | In dev-tool repo descriptions, almost always GitHub Copilot |
| Codex | bare match on `"codex"` | OpenAI Codex is the dominant modern meaning in dev contexts |
| Cursor | bare match + 80-char context window | Bare "cursor" hits DB cursors / mouse cursors too often; need either a list-intro phrase OR another assistant name nearby |

**Validation against `Lum1104/Understand-Anything`:**

Description: `"Graphs that teach > graphs that impress. Turn any code into an interactive knowledge graph you can explore, search, and ask questions about. Works with Claude Code, Codex, Cursor, Copilot, Gemini CLI, and more."`

- `"claude code"` present → `claude-code` ✓
- `"codex"` present → `codex` ✓
- `"copilot"` present → `copilot` ✓
- `"cursor"` present; 80-char window contains `"Works with"` (list intro) AND `"Claude Code"`, `"Codex"`, `"Copilot"` → `cursor` ✓

Result: `{claude-code, codex, copilot, cursor}` — matches the repo's declared targets.

**Validation against false-positive cases:**

- `"Iterate database results using a cursor"` — 80-char window around "cursor" has no list-intro and no other assistant name → no tag ✓
- `"Restores Vim cursor position on file open"` — same → no tag ✓
- `"Codex of ancient texts"` — gets tagged `codex` (false positive accepted in v1; affects only entries that pass our source-hint funnel, which themselves filter heavily for assistant-related repos)

## Discovery Workflow Changes

Add three steps to `.github/workflows/discover.yml` immediately after the existing "Commit additions" step:

```yaml
      - name: Checkout data branch (for re-render)
        if: success()
        uses: actions/checkout@v4
        with:
          ref: data
          path: data-branch

      - name: Re-render rankings with new entries
        if: success()
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          MAIN_DIR: ${{ github.workspace }}
          DATA_DIR: ${{ github.workspace }}/data-branch
        run: python -m scripts.scrape

      - name: Commit & push rendered output
        if: success()
        run: |
          git add README.md rankings/ data/latest.json
          if git diff --cached --quiet; then
            echo "No render diff."
          else
            git commit -m "Re-render after discovery ($(date -u +%Y-%m-%d))"
            git push origin main
          fi
          cd data-branch
          git add snapshots/
          if git diff --cached --quiet; then
            echo "No snapshot diff."
          else
            git commit -m "Snapshot $(date -u +%Y-%m-%d) (post-discovery)"
            git push origin data
          fi
```

**Notes:**

- All three steps gated on `if: success()` — if discovery itself failed, we skip re-rendering.
- `scripts.scrape` is the existing daily orchestrator; it reads `plugins.yaml`, fetches stars, writes `latest.json`, renders all markdown files, and writes today's snapshot to the data branch. No new rendering code.
- The re-render `scripts.scrape` runs will overwrite today's snapshot if one already exists (the daily cron may have run earlier). `write_snapshot` is already idempotent — same input produces byte-identical output.
- Cost: one extra full scrape pass (~5–10 min wall clock for ~400 plugins) and one extra commit per branch per discovery run.

**Side benefit:** the daily cron's primary job (fetching star deltas + re-rendering) now also runs as part of discovery, so users who land within minutes of a discovery run see fresh tables.

## `scripts/retag.py`

One-off CLI for manual re-evaluation of every entry in `plugins.yaml` after the algorithm change.

```python
"""Re-evaluate every entry in plugins.yaml against the current
resolve_assistants logic. Useful after algorithm changes.

Not wired into any cron. Run manually after merging the algorithm fix:
    GITHUB_TOKEN=$(gh auth token) python -m scripts.retag

Behavior: for each entry, fetch the repo's current description, re-run
resolve_assistants with no source hints (since hint history isn't stored),
and update the entry's assistants list if the result is non-empty AND
differs from the stored value."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ruamel.yaml import YAML

from scripts.discover import resolve_assistants
from scripts.github_api import GitHubClient, RepoMissingError

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def retag_all(yaml_path: Path, gh: GitHubClient) -> int:
    """Returns the number of entries updated."""
    with yaml_path.open("r", encoding="utf-8") as f:
        doc = _yaml.load(f)
    changed = 0
    for entry in doc["plugins"]:
        try:
            data = gh.fetch_repo(entry["repo"])
        except RepoMissingError:
            continue
        new = sorted(resolve_assistants(data, set(), readme=None))
        if new and list(entry["assistants"]) != new:
            entry["assistants"] = new
            changed += 1
    if changed:
        with yaml_path.open("w", encoding="utf-8") as f:
            _yaml.dump(doc, f)
    return changed


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)
    gh = GitHubClient(token=token)
    try:
        n = retag_all(Path("plugins.yaml"), gh)
    finally:
        gh.close()
    print(f"Updated {n} entries.")


if __name__ == "__main__":
    main()
```

**Why manual-only:** retag walks ~400 entries and mutates an existing `plugins.yaml`. A buggy retag could re-tag the whole registry incorrectly. Keeping it human-triggered means the user reviews `git diff plugins.yaml` before committing.

**Cost:** ~366 API calls (one per entry). Well inside the 5,000/hr budget.

## Error Handling

| Failure | Behavior |
|---|---|
| Discovery workflow's discovery step fails | Re-render steps are skipped (`if: success()`) |
| Re-render step's scrape fails | Workflow fails; failure-issue step opens an issue. plugins.yaml stays updated from the discovery commit |
| Re-render finds no diff | `git diff --cached --quiet` → no commit; clean exit |
| retag's GitHub call 404s on a missing repo | Skip that entry, continue |
| retag rate-limit | Existing `RateLimitError` bubbles up; the YAML hasn't been written yet so plugins.yaml is unchanged |
| retag finds zero changes | No write; print `Updated 0 entries.` |

## Testing

**New tests in `tests/test_discover.py`** (existing 13 tests stay):

- `test_resolve_assistants_codex_bare` — `"Tool for Codex and other agents"` → tags codex
- `test_resolve_assistants_copilot_bare` — `"A Copilot plugin"` → tags copilot
- `test_resolve_assistants_understand_anything` — full Understand-Anything description → all four tags
- `test_resolve_assistants_cursor_in_list_context` — `"Works with Claude Code and Cursor"` → tags cursor
- `test_resolve_assistants_db_cursor_not_tagged` — `"Iterate database results using a cursor"` → no cursor tag

**Existing tests to update:**

- `test_resolve_assistants_cursor_requires_context` — current assertion `"cursor" not in out` for the description `"Returns a DB cursor row by row"` is preserved by the new algorithm (window has no list-intro and no other assistant) → no change needed
- `test_resolve_assistants_cursor_with_ide_context` — current description `"Cursor editor extension for refactoring"` — under new algorithm, the window around "cursor" contains `"for"` (a list-intro phrase that has been widened) → still tags cursor. Test passes unchanged.
- `test_resolve_assistants_adds_from_readme` — uses description `"A plugin for Claude Code and OpenAI Codex"` → now `"codex"` triggers bare match, `"claude code"` triggers claude match → `{claude-code, codex}` ✓
- `test_resolve_assistants_uses_hints` — `description="Some tool"` with hint `{cursor}` → still returns `{cursor}` ✓ (cursor hint already in out)

**New test file `tests/test_retag.py`:**

- `test_retag_updates_when_description_indicates_more_assistants` — given a seed YAML with `assistants: [claude-code]` and a mocked `fetch_repo` returning a description that triggers all four matchers, the YAML should end with `assistants: [claude-code, codex, copilot, cursor]`
- `test_retag_no_change_when_description_matches_current` — same in/out; no write
- `test_retag_skips_missing_repo` — RepoMissingError on one entry; others still processed; YAML reflects partial updates

**Integration:** no new integration test; the existing `tests/test_discover_integration.py` covers the orchestrator path. The retag flow is its own CLI; covered by unit tests above.

## Migration / Rollout

1. Land the code changes.
2. Run `make discover-smoke` locally **only after** the rate-limit budget refills (likely tomorrow).
3. Run `GITHUB_TOKEN=$(gh auth token) python -m scripts.retag` locally.
4. Inspect `git diff plugins.yaml`. Expected: many `[claude-code]` entries gain Codex/Cursor/Copilot tags where descriptions support them. `Lum1104/Understand-Anything` should land at `[claude-code, codex, copilot, cursor]`.
5. Commit + push.
6. The next daily cron (or the next discovery run, which now also renders) will refresh `README.md` and `rankings/*.md` with the corrected tags.

## Open Questions

- **False-positive rate on bare "Copilot" / "Codex".** The dev-tooling assumption is strong but not airtight. If post-rollout we see clearly-wrong tags (e.g. a Microsoft Office Copilot helper getting tagged copilot when it has nothing to do with GitHub Copilot), tighten the regex by adding a co-occurrence requirement similar to Cursor. The existing 366 entries will tell us if this is a real problem.
- **Multi-language descriptions.** We lowercase + ASCII-match. A Chinese description that says `克劳德 Code` would still match the `claude` part of `"claude code"`. Non-English-only descriptions for plugins explicitly targeting these four assistants will miss. Out of scope for v1; logged in this section so future iteration sees it.

## Future (out of scope here)

- Re-introduce selective README fetching for low-signal descriptions (`if len(description) < 30: fetch_readme(...)`)
- Per-assistant confidence scoring instead of binary tags
- Crowd-sourced tag corrections via PR (the maintainer can already do this; future feature could surface PR comments as overrides)
