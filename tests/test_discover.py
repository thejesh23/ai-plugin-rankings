from pathlib import Path
from unittest.mock import MagicMock

from scripts.discover import is_plugin_signal, resolve_assistants, run_discover
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


# --- is_plugin_signal -------------------------------------------------------

def test_is_plugin_signal_code_search_always_passes() -> None:
    """github_code_search matches mean the repo has a manifest file."""
    assert is_plugin_signal("anything", "no markers here", "github_code_search")


def test_is_plugin_signal_plugin_in_name() -> None:
    assert is_plugin_signal("my-plugin", "", "awesome_list")
    assert is_plugin_signal("Cool-Skill", "", "awesome_list")
    assert is_plugin_signal("foo-mcp-server", "", "awesome_list")


def test_is_plugin_signal_description_with_assistant_and_plugin_word() -> None:
    assert is_plugin_signal(
        "x", "A plugin for Claude Code", "awesome_list")
    assert is_plugin_signal(
        "x", "Skill collection for Cursor users", "awesome_list")


def test_is_plugin_signal_agentic_framework() -> None:
    """obra/superpowers case: 'agentic skills framework' should pass."""
    assert is_plugin_signal(
        "superpowers",
        "An agentic skills framework and software development methodology",
        "manual",
    )


def test_is_plugin_signal_rejects_n8n() -> None:
    """n8n's description doesn't contain plugin or assistant markers."""
    assert not is_plugin_signal(
        "n8n",
        "Free and source-available fair-code licensed workflow automation tool",
        "awesome_list",
    )


def test_is_plugin_signal_rejects_generic_prompt_lib() -> None:
    assert not is_plugin_signal(
        "prompts.chat",
        "This repo includes ChatGPT prompt curation",
        "awesome_list",
    )


def test_discover_filters_non_plugin(tmp_path: Path) -> None:
    """A high-star repo with no plugin signals is skipped at orchestration."""
    yaml, log = _seed(tmp_path)
    gh = MagicMock()
    gh.fetch_repo.return_value = _repo(
        "o/n8n-like", 100_000,
        description="Workflow automation tool. Self-host or use cloud.",
    )
    s = MagicMock()
    s.name = "awesome_list"
    s.fetch_candidates.return_value = [RawCandidate(
        repo="o/n8n-like", source="awesome_list", hint_assistants=["claude-code"])]
    additions = run_discover(yaml, log, [s], gh,
        today="2026-05-29", disabled=set())
    assert additions == []
    assert "o/n8n-like" not in yaml.read_text()
