from scripts.constants import ASSISTANTS, CATEGORIES, TAGS


def test_categories_are_unique_strings() -> None:
    assert len(CATEGORIES) == len(set(CATEGORIES))
    assert all(isinstance(c, str) for c in CATEGORIES)
    assert "productivity" in CATEGORIES
    assert "other" in CATEGORIES  # fallback bucket must exist


def test_tags_are_unique_strings() -> None:
    assert len(TAGS) == len(set(TAGS))
    assert all(isinstance(t, str) for t in TAGS)


def test_assistants_set() -> None:
    assert {"claude-code", "cursor", "copilot", "codex"} == ASSISTANTS
