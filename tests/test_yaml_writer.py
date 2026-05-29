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
