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
    by_id = {p.id: set(p.assistants) for p in reg.plugins}
    assert by_id["a"] == {"claude-code"}
    assert by_id["b"] == {"claude-code", "codex"}
