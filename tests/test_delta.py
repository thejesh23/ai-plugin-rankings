from scripts.delta import compute_delta
from scripts.models import SnapshotRow


def row(id: str, stars: int) -> SnapshotRow:
    return SnapshotRow(id=id, repo=f"o/{id}", stars=stars, forks=0,
                       open_issues=0, archived=False, pushed_at="2026-05-27T00:00:00Z")


def test_delta_basic() -> None:
    today = [row("a", 100), row("b", 50)]
    yesterday = [row("a", 90), row("b", 50)]
    assert compute_delta(today, yesterday) == {"a": 10, "b": 0}


def test_delta_new_plugin_returns_none() -> None:
    """A plugin not in 'previous' has no delta — neither 0 nor stars."""
    today = [row("new", 25)]
    yesterday: list[SnapshotRow] = []
    assert compute_delta(today, yesterday) == {"new": None}


def test_delta_missing_previous_means_none_for_all() -> None:
    today = [row("a", 100)]
    assert compute_delta(today, None) == {"a": None}


def test_delta_handles_unstarred_decline() -> None:
    """Stars can go down (unstar). Delta can be negative."""
    today = [row("a", 50)]
    yesterday = [row("a", 80)]
    assert compute_delta(today, yesterday) == {"a": -30}
