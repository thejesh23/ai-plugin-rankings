# Tagging Algorithm Fix + Auto-Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `resolve_assistants` to correctly catch multi-target plugins, add a one-off `retag.py` CLI to re-evaluate the existing 366 entries, and make the discovery workflow re-render rankings inline so new entries show up in README minutes after auto-add.

**Architecture:** Two-line regex change to `resolve_assistants` (broader bare-name matches + 80-char window check for Cursor). New small `scripts/retag.py` that round-trips `plugins.yaml` via `ruamel.yaml` calling the updated `resolve_assistants` for every entry. Three new steps in `.github/workflows/discover.yml` that re-invoke the existing `scripts.scrape` orchestrator after auto-add and push the rendered output.

**Tech Stack:** Python 3.12, existing deps (no new deps).

**Repo root:** `/Users/thejesh/Git/ai-plugin-rankings`. On `main`, last commit `8134198` (the design spec).

**Spec reference:** `docs/superpowers/specs/2026-05-29-tagging-fix-design.md`

---

## Task 1: Rewrite `resolve_assistants` with looser matchers + Cursor window check

**Files:**
- Modify: `scripts/discover.py:46-60` (the existing `resolve_assistants` function)
- Modify: `tests/test_discover.py` (append 5 new tests)

- [ ] **Step 1: Append the 5 new tests**

Open `tests/test_discover.py` and append at the END of the file:

```python
# --- New resolve_assistants behavior (2026-05-29 tagging fix) ----------------

def test_resolve_assistants_codex_bare() -> None:
    """Bare 'Codex' in description should tag codex (was previously a miss)."""
    data = _repo("o/x", 1000, description="Tool for Codex and other agents")
    assert "codex" in resolve_assistants(data, set(), readme=None)


def test_resolve_assistants_copilot_bare() -> None:
    """Bare 'Copilot' in description should tag copilot (was previously a miss)."""
    data = _repo("o/x", 1000, description="A Copilot plugin")
    assert "copilot" in resolve_assistants(data, set(), readme=None)


def test_resolve_assistants_understand_anything() -> None:
    """Real-world regression: Lum1104/Understand-Anything's description should
    yield all four assistant tags."""
    data = _repo("o/x", 1000, description=(
        "Graphs that teach. Turn any code into an interactive knowledge graph "
        "you can explore, search, and ask questions about. Works with Claude "
        "Code, Codex, Cursor, Copilot, Gemini CLI, and more."))
    out = resolve_assistants(data, set(), readme=None)
    assert out == {"claude-code", "codex", "copilot", "cursor"}


def test_resolve_assistants_cursor_in_list_context() -> None:
    """'Cursor' inside a 'works with' list should tag cursor."""
    data = _repo("o/x", 1000,
                 description="Works with Claude Code and Cursor")
    assert "cursor" in resolve_assistants(data, set(), readme=None)


def test_resolve_assistants_db_cursor_not_tagged() -> None:
    """'cursor' in a database context should NOT tag cursor.
    Window has no list-intro phrase and no other assistant name."""
    data = _repo("o/x", 1000,
                 description="Iterate database results using a cursor")
    assert "cursor" not in resolve_assistants(data, set(), readme=None)
```

Add `-> None` annotations are already in the snippet — no further action.

- [ ] **Step 2: Run tests to confirm 4 of them fail under the OLD algorithm**

Run: `source .venv/bin/activate && pytest tests/test_discover.py -v 2>&1 | tail -20`

Expected: the four new "bare match" tests FAIL (codex, copilot, understand_anything, cursor_in_list_context); the db-cursor test should already PASS (the old algorithm also avoided tagging in that case). All existing 13 tests still PASS. Concretely you should see something like:

```
FAILED tests/test_discover.py::test_resolve_assistants_codex_bare
FAILED tests/test_discover.py::test_resolve_assistants_copilot_bare
FAILED tests/test_discover.py::test_resolve_assistants_understand_anything
FAILED tests/test_discover.py::test_resolve_assistants_cursor_in_list_context
========= 14 passed, 4 failed in X.XXs =========
```

If any of the 13 existing tests fail, STOP — the new tests have collided with existing behavior and the existing tests must be re-examined first.

- [ ] **Step 3: Open `scripts/discover.py` and update imports**

At the top of `scripts/discover.py`, find the existing imports and add `re` to the imports block. The existing import block looks like:

```python
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
```

Change it to:

```python
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
```

- [ ] **Step 4: Add the two regex constants below `KNOWN_ASSISTANTS`**

Find the existing line `KNOWN_ASSISTANTS = {"claude-code", "cursor", "copilot", "codex"}` in `scripts/discover.py`. Immediately AFTER it, add:

```python


# Phrases that suggest a real plugin context (list intros AND product-type
# nouns). Includes "extension/editor/ide/rules" so Cursor descriptions like
# "Cursor editor extension" still match. Excludes bare "for" to avoid false
# positives like "cursor for the database".
_LIST_INTRO_RE = re.compile(
    r"\b(?:works?\s+with|supports?|compatible\s+with|plugin\s+for|"
    r"plugins?\s+for|integrates?\s+with|plugin|extension|editor|ide|rules)\b",
    re.IGNORECASE,
)

# Any of the other three assistant names — used for Cursor co-occurrence check.
_OTHER_ASSISTANT_RE = re.compile(
    r"\b(?:claude(?:\s+code|-code)?|copilot|codex)\b",
    re.IGNORECASE,
)
```

- [ ] **Step 5: Replace the body of `resolve_assistants`**

Find the existing `resolve_assistants` function in `scripts/discover.py`. Replace the ENTIRE function definition with:

```python
def resolve_assistants(
    data: RepoData, hints: set[str], readme: str | None,
) -> set[str]:
    """Determine which assistants a plugin targets.

    Operates on the GitHub repo description plus any source hints. The
    orchestrator deliberately does NOT pass a readme (see bulk-discovery
    design for the rate-limit rationale); the readme param is kept so unit
    tests can drive specific scenarios."""
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

The previous body relied on `readme` to build the text blob; the new body uses only `data.description`. The `readme` parameter is preserved in the signature (for backwards compat with the existing tests that pass `readme=None`).

- [ ] **Step 6: Run tests to verify all 18 pass and gates are clean**

Run:
```bash
source .venv/bin/activate
pytest tests/test_discover.py -v
mypy scripts tests
ruff check .
```

Expected: 18 tests pass (13 existing + 5 new), mypy clean, ruff clean.

If a test fails: re-read step 5 carefully — the most common bug is forgetting to delete the old body before pasting the new one.

- [ ] **Step 7: Commit**

```bash
git add scripts/discover.py tests/test_discover.py
git commit -m "discover: looser resolve_assistants with Cursor window check"
```

---

## Task 2: Create `scripts/retag.py` + tests

**Files:**
- Create: `scripts/retag.py`
- Create: `tests/test_retag.py`

- [ ] **Step 1: Write the failing test** — `tests/test_retag.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from scripts.github_api import RepoData, RepoMissingError
from scripts.plugins_yaml import load_registry
from scripts.retag import retag_all


def _repo(repo: str, description: str = "") -> RepoData:
    return RepoData(
        repo=repo, stars=5000, forks=0, open_issues=0,
        archived=False, pushed_at="2026-05-28T00:00:00Z",
        description=description,
    )


SEED_ONE_ENTRY = """\
# header

plugins:
  - id: understand-anything
    repo: Lum1104/Understand-Anything
    assistants:
      - claude-code
    added: "2026-05-29"
"""


def test_retag_updates_when_description_indicates_more_assistants(
    tmp_path: Path,
) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_ONE_ENTRY)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo(
        "Lum1104/Understand-Anything",
        description=("Graphs that teach. Works with Claude Code, Codex, "
                     "Cursor, Copilot, Gemini CLI, and more."),
    )
    n = retag_all(yaml, gh)
    assert n == 1
    reg = load_registry(yaml)
    assert set(reg.plugins[0].assistants) == {
        "claude-code", "codex", "copilot", "cursor"}


def test_retag_no_change_when_description_matches_current(tmp_path: Path) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_ONE_ENTRY)
    before = yaml.read_text()
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo(
        "Lum1104/Understand-Anything",
        description="A Claude Code workflow framework",
    )
    n = retag_all(yaml, gh)
    assert n == 0
    assert yaml.read_text() == before


def test_retag_skips_missing_repo(tmp_path: Path) -> None:
    """If a repo 404s, that entry is skipped and others continue."""
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text("""\
# header

plugins:
  - id: a
    repo: o/a
    assistants:
      - claude-code
    added: "2026-05-28"
  - id: b
    repo: o/b
    assistants:
      - claude-code
    added: "2026-05-28"
""")
    gh = MagicMock()

    def side_effect(repo: str) -> RepoData:
        if repo == "o/a":
            raise RepoMissingError("o/a")
        return _repo(repo, description="Works with Claude Code, Codex")
    gh.fetch_repo.side_effect = side_effect

    n = retag_all(yaml, gh)
    assert n == 1
    reg = load_registry(yaml)
    # 'a' keeps its old assistants; 'b' was updated to include codex
    by_id = {p.id: set(p.assistants) for p in reg.plugins}
    assert by_id["a"] == {"claude-code"}
    assert by_id["b"] == {"claude-code", "codex"}
```

Add `-> None` annotations (already in the snippet).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retag.py -v`
Expected: FAIL — `scripts.retag` module does not exist.

- [ ] **Step 3: Implement `scripts/retag.py`**

```python
"""Re-evaluate every entry in plugins.yaml against the current
resolve_assistants logic. Useful after the algorithm changes.

Not wired into any cron. Run manually after merging an algorithm change:
    GITHUB_TOKEN=$(gh auth token) python -m scripts.retag
"""
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
    """Re-evaluate assistants for every entry in plugins.yaml.

    Returns the number of entries updated. Does not write the file if
    nothing changed. Uses no source hints (hint history isn't persisted)."""
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

- [ ] **Step 4: Run tests + gates**

Run:
```bash
source .venv/bin/activate
pytest tests/test_retag.py -v
mypy scripts tests
ruff check .
```

Expected: 3 tests pass, mypy clean, ruff clean.

If mypy complains about `_yaml.load(f)` returning `Any`, add a minimal `# type: ignore[no-any-unimported]` only on the specific line that triggers the error. The pattern already proven to work cleanly in `scripts/yaml_writer.py` — match what's there.

- [ ] **Step 5: Commit**

```bash
git add scripts/retag.py tests/test_retag.py
git commit -m "Add retag.py: one-off CLI to re-evaluate existing assistant tags"
```

---

## Task 3: Update `.github/workflows/discover.yml` to re-render after auto-add

**Files:**
- Modify: `.github/workflows/discover.yml`

- [ ] **Step 1: Read the current workflow to find the insertion point**

The current workflow has these steps in order:
1. Checkout
2. Setup Python
3. Install
4. Configure git
5. Run discovery
6. Commit additions
7. Open issue on failure

We need to insert the three new steps BETWEEN step 6 ("Commit additions") and step 7 ("Open issue on failure").

- [ ] **Step 2: Insert the three new steps**

Open `.github/workflows/discover.yml`. Find the line that begins the "Open issue on failure" step (it starts with `- name: Open issue on failure`). Immediately BEFORE that line, insert these three steps:

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

Indentation MUST match the surrounding steps (6 spaces before `- name:`). If you accidentally use 4 or 8, the YAML will parse but the steps won't be inside the job — verify in step 3.

- [ ] **Step 3: Validate YAML parses and the steps land in the right job**

Run:
```bash
source .venv/bin/activate
python -c "
import yaml
with open('.github/workflows/discover.yml') as f:
    doc = yaml.safe_load(f)
steps = doc['jobs']['discover']['steps']
names = [s.get('name', s.get('uses', '???')) for s in steps]
print(f'{len(steps)} steps:')
for n in names:
    print(f'  - {n}')
"
```

Expected output: 10 steps in the `discover` job, in this order:

```
10 steps:
  - actions/checkout@v4
  - actions/setup-python@v5
  - Install
  - Configure git
  - Run discovery
  - Commit additions
  - Checkout data branch (for re-render)
  - Re-render rankings with new entries
  - Commit & push rendered output
  - Open issue on failure
```

If you see a different count or order, the indentation is wrong — fix and re-validate.

- [ ] **Step 4: Run full gates**

Run:
```bash
pytest -v && mypy scripts tests && ruff check .
```

Expected: all tests pass (count should now be 95 from v1 + 5 new resolve_assistants + 3 new retag = 103), mypy + ruff clean.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/discover.yml
git commit -m "discover.yml: re-render rankings after auto-add"
```

---

## Task 4: Push, run retag locally, verify, push retag commit

This is the manual rollout step. It's NOT wired into the workflow because the retag mutates the existing 366 entries and a buggy retag could mangle the registry — the user reviews the diff before pushing.

- [ ] **Step 1: Push the code changes**

```bash
git push origin main
```

This pushes the three commits from Tasks 1–3.

- [ ] **Step 2: Run the retag CLI locally**

Set up the token and run:

```bash
source .venv/bin/activate
GITHUB_TOKEN=$(gh auth token) python -m scripts.retag
```

Expected output: `Updated N entries.` for some N between 0 and 366. Many of the existing 354 auto-added entries had `[claude-code]` only despite supporting more — those will get their assistants list expanded. Expect N to be in the dozens.

Note: this makes one GitHub API call per entry (one `fetch_repo` per repo, total ~366 calls). Stays inside the 5000/hr standard rate budget. If you've recently exhausted your local rate budget, run `gh api rate_limit --jq '.resources.core'` first to check `remaining` is comfortably above 400.

If the run errors with `RateLimitError`, wait until the `reset` timestamp passes (`date -r <reset_epoch>`) and retry. The retag is idempotent — already-updated entries no-op on a re-run.

- [ ] **Step 3: Inspect the diff**

Run:
```bash
git diff plugins.yaml | head -60
```

Expected: many small block-style diffs that add codex/cursor/copilot to entries that previously had only `[claude-code]`. Critically:

```bash
git diff plugins.yaml | grep -A 5 "Lum1104/Understand-Anything"
```

The `Lum1104/Understand-Anything` entry should now have `assistants: [claude-code, codex, copilot, cursor]` (block-style, four entries).

If the diff looks broken (e.g. mass deletions, entries reordered, YAML keys reshuffled), STOP and investigate — `git checkout plugins.yaml` to revert and debug.

- [ ] **Step 4: Commit and push the retag result**

```bash
git add plugins.yaml
git commit -m "Retag: re-evaluate existing entries with new resolve_assistants"
git push origin main
```

- [ ] **Step 5: Optionally trigger discovery to see the auto-render in action**

If you want immediate visual confirmation that the auto-render flow works:

```bash
gh workflow run "Weekly discovery"
sleep 10
RUN=$(gh run list --workflow="Weekly discovery" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN --exit-status
```

Expected: the workflow runs all 10 steps green (or 9 if "Open issue on failure" is skipped — which it should be on success). After it completes, README.md on origin/main should include Understand-Anything with its full multi-assistant tag in the table.

If discovery finds no new candidates this run (likely, since we already auto-added 354 last Sunday), the "Commit additions" step prints `No new plugins this run.` and exits clean — the re-render still runs and updates README with the retagged data.

- [ ] **Step 6: Final commit (none required)**

This task is verification + manual rollout; nothing further to commit.

---

## Self-Review

Cross-checked the plan against the spec:

| Spec section | Implementing task(s) |
|---|---|
| New `resolve_assistants` algorithm | T1 (rewrite + 5 new tests) |
| `_LIST_INTRO_RE` and `_OTHER_ASSISTANT_RE` regex constants | T1 step 4 |
| Cursor 80-char window check | T1 step 5 |
| `scripts/retag.py` CLI | T2 |
| 3 unit tests for retag (update / no-change / missing-repo) | T2 step 1 |
| Discovery workflow re-render steps | T3 |
| `if: success()` gating + idempotent commit checks | T3 step 2 (YAML body) |
| Manual rollout: push → retag → verify → push | T4 |

No placeholders. No "implement later" / "add appropriate handling" / "similar to task N".

Type / signature consistency:
- `resolve_assistants(data: RepoData, hints: set[str], readme: str | None) -> set[str]` — signature unchanged from current; only body replaced. All existing callers and tests still work.
- `retag_all(yaml_path: Path, gh: GitHubClient) -> int` — defined in T2 step 3, used identically in T2's three tests.
- The `_yaml` instance in `scripts/retag.py` mirrors the pattern already used in `scripts/yaml_writer.py` — consistent across the codebase.
- The workflow's 3 new steps reference `${{ github.workspace }}` and env vars consistent with the existing `daily.yml`.

---

## Notes for the executor

- **TDD discipline**: T1 writes 5 new tests, runs them to confirm 4 fail under the old code, then rewrites `resolve_assistants` and re-runs to confirm 18 pass.
- **Be careful with the regex literal**: in step 4 of T1, the `_LIST_INTRO_RE` regex spans two source lines (raw string with continuation). Copy verbatim; do not reflow the line.
- **YAML indentation in T3** is the most common failure mode. The validation script in step 3 catches misplacement.
- **T4 step 2 (running retag locally)** requires a fresh-enough rate budget. If you ran any discovery smokes recently, check `gh api rate_limit` first.
- **T4 is a one-time manual step**. Subsequent algorithm changes would re-run this task; it's not on a cron and shouldn't be.
