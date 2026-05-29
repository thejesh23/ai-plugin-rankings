from pathlib import Path
from unittest.mock import MagicMock

from scripts.github_api import RepoData
from scripts.purge import find_purge_candidates, write_candidates_file


def _repo(repo: str, description: str = "") -> RepoData:
    return RepoData(
        repo=repo, stars=5000, forks=0, open_issues=0,
        archived=False, pushed_at="2026-05-28T00:00:00Z",
        description=description,
    )


def test_seed_ids_immune(tmp_path: Path) -> None:
    """An entry in MANUAL_SEED_IDS is never flagged, even with a vague description."""
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text("""\
# header

plugins:
  - id: superpowers
    repo: obra/superpowers
    assistants: [claude-code]
    added: "2026-05-28"
""")
    gh = MagicMock()
    # Description with no plugin/assistant markers would normally fail.
    gh.fetch_repo.return_value = _repo("obra/superpowers", description="vague")
    candidates = find_purge_candidates(yaml, gh, throttle=0)
    assert candidates == []
    gh.fetch_repo.assert_not_called()  # seeds skipped before API call


def test_flags_non_plugin_entry(tmp_path: Path) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text("""\
# header

plugins:
  - id: n8n
    repo: n8n-io/n8n
    assistants:
      - claude-code
    added: "2026-05-29"
""")
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo(
        "n8n-io/n8n",
        description="Free workflow automation tool. Self-host or use cloud.",
    )
    candidates = find_purge_candidates(yaml, gh, throttle=0)
    assert len(candidates) == 1
    assert candidates[0][0] == "n8n"
    assert candidates[0][1] == "n8n-io/n8n"


def test_keeps_plugin_with_assistant_in_description(tmp_path: Path) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text("""\
# header

plugins:
  - id: real-plugin
    repo: someone/real-plugin
    assistants:
      - claude-code
    added: "2026-05-29"
""")
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo(
        "someone/real-plugin",
        description="A plugin for Claude Code that does things",
    )
    candidates = find_purge_candidates(yaml, gh, throttle=0)
    assert candidates == []


def test_write_candidates_file_format(tmp_path: Path) -> None:
    out = tmp_path / "purge-candidates.txt"
    write_candidates_file(
        [("badone", "o/badone", "Some non-plugin tool"),
         ("aone", "o/aone", "Another tool")],
        out,
    )
    content = out.read_text()
    assert "# Purge candidates" in content
    # Entries sorted alphabetically
    a_idx = content.index("aone")
    b_idx = content.index("badone")
    assert a_idx < b_idx
    # Tab-separated
    assert "aone\to/aone\tAnother tool" in content
