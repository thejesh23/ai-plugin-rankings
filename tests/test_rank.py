from scripts.models import LatestPlugin
from scripts.rank import rank_by_stars, rank_by_trending


def plug(
    id: str, stars: int, stars_24h: int | None = 0,
    archived: bool = False, status: str = "ok",
) -> LatestPlugin:
    return LatestPlugin(
        id=id, repo=f"o/{id}", assistants=["claude-code"],
        stars=stars, stars_24h=stars_24h, stars_7d=None,
        previous_stars=stars - (stars_24h or 0), archived=archived,
        status=status, url=f"https://github.com/o/{id}",  # type: ignore[arg-type]
    )


def test_rank_by_stars_descending() -> None:
    plugins = [plug("a", 100), plug("b", 50), plug("c", 200)]
    ranked = rank_by_stars(plugins)
    assert [p.id for p in ranked] == ["c", "a", "b"]


def test_rank_archived_sorts_to_bottom() -> None:
    plugins = [
        plug("a", 100), plug("z-archived", 500, archived=True), plug("b", 50),
    ]
    ranked = rank_by_stars(plugins)
    assert [p.id for p in ranked] == ["a", "b", "z-archived"]


def test_rank_by_trending_descending_by_24h() -> None:
    plugins = [plug("a", 100, stars_24h=5), plug("b", 50, stars_24h=20),
               plug("c", 200, stars_24h=1)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["b", "a", "c"]


def test_rank_by_trending_none_delta_sorts_to_bottom() -> None:
    """Plugins with no delta (new, no history) rank below those with 0."""
    plugins = [plug("a", 100, stars_24h=None), plug("b", 50, stars_24h=0)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["b", "a"]


def test_rank_by_trending_ties_broken_by_total_stars() -> None:
    plugins = [plug("low", 50, stars_24h=10), plug("high", 500, stars_24h=10)]
    ranked = rank_by_trending(plugins)
    assert [p.id for p in ranked] == ["high", "low"]
