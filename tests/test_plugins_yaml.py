from pathlib import Path

import pytest

from scripts.plugins_yaml import load_registry

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_good_registry() -> None:
    reg = load_registry(FIXTURES / "plugins-good.yaml")
    assert len(reg.plugins) == 2
    assert reg.plugins[0].id == "superpowers"


def test_load_duplicate_ids_raises() -> None:
    with pytest.raises(ValueError, match="duplicate plugin ids"):
        load_registry(FIXTURES / "plugins-bad-duplicate.yaml")


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "nope.yaml")
