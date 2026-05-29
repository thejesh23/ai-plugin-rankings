from pathlib import Path
from unittest.mock import MagicMock

from scripts.discover import resolve_assistants, run_discover
from scripts.github_api import RepoData, RepoMissingError
from scripts.sources.base import RawCandidate


def _repo(repo: str, stars: int, archived: bool = False,
          description: str = "") -> RepoData:
    return RepoData(
        repo=repo, stars=stars, forks=0, open_issues=0,
        archived=archived, pushed_at="2026-05-28T00:00:00Z",
        description=description,
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
    s1 = MagicMock()
    s1.name = "src1"
    s1.fetch_candidates.return_value = [RawCandidate(
        repo="o/multi", source="src1", hint_assistants=["claude-code"])]
    s2 = MagicMock()
    s2.name = "src2"
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
    src = MagicMock()
    src.name = "naughty"
    run_discover(yaml, log, [src], gh, today="2026-05-29",
                 disabled={"naughty"})
    src.fetch_candidates.assert_not_called()


def test_failing_source_does_not_abort_run(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/ok", 5000,
        description="Claude Code plugin")
    gh.fetch_readme.return_value = ""
    bad = MagicMock()
    bad.name = "bad"
    bad.fetch_candidates.side_effect = RuntimeError("boom")
    good = MagicMock()
    good.name = "good"
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
    s = MagicMock()
    s.name = "s"
    s.fetch_candidates.return_value = [RawCandidate(
        repo="o/gone", source="s", hint_assistants=["claude-code"])]
    run_discover(yaml, log, [s], gh, today="2026-05-29", disabled=set())
    assert "o/gone" not in yaml.read_text()


def test_no_assistants_resolved_skipped(tmp_path: Path) -> None:
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo("o/x", 5000, description="Unrelated tool")
    gh.fetch_readme.return_value = "Just a tool"
    s = MagicMock()
    s.name = "s"
    s.fetch_candidates.return_value = [RawCandidate(
        repo="o/x", source="s", hint_assistants=[])]
    run_discover(yaml, log, [s], gh, today="2026-05-29", disabled=set())
    assert "o/x" not in yaml.read_text()
