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
        description=desc,
    )


def test_full_orchestrator_with_three_stub_sources(tmp_path: Path) -> None:
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_YAML)
    log = tmp_path / "discovery.log"

    src1 = MagicMock()
    src1.name = "src1"
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
    src2 = MagicMock()
    src2.name = "src2"
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
                description="Claude Code plugin",
            ),
        }[repo]
    gh.fetch_repo.side_effect = fetch_repo
    gh.fetch_readme.return_value = ""

    additions = run_discover(yaml, log, [src1, src2], gh,
                             today="2026-05-29", disabled=set())
    repos_added = {a.repo for a in additions}
    assert repos_added == {"o/big1", "o/big2"}

    big2 = next(a for a in additions if a.repo == "o/big2")
    assert set(big2.via) == {"src1", "src2"}
    assert set(big2.assistants) == {"claude-code", "codex"}

    reg = load_registry(yaml)
    assert {p.repo for p in reg.plugins} == {
        "obra/superpowers", "o/big1", "o/big2",
    }

    log_text = log.read_text().splitlines()
    assert len(log_text) == 2
    assert any("o/big1" in line and "2500 stars" in line for line in log_text)
    assert any("o/big2" in line and "via=src1,src2" in line for line in log_text)

    assert "# Curated registry" in yaml.read_text()


def test_no_qualifying_candidates_no_writes(tmp_path: Path) -> None:
    """When nothing qualifies, plugins.yaml and discovery.log untouched."""
    yaml = tmp_path / "plugins.yaml"
    yaml.write_text(SEED_YAML)
    log = tmp_path / "discovery.log"
    before = yaml.read_text()

    src = MagicMock()
    src.name = "s"
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
