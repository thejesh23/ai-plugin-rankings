"""Sort plugins for the two ranking views.

Both rankings push archived plugins to the bottom — they're tracked for
historical interest but shouldn't dominate the visible top of any list."""
from scripts.models import LatestPlugin


def rank_by_stars(plugins: list[LatestPlugin]) -> list[LatestPlugin]:
    return sorted(
        plugins,
        # Archived first (True > False), then descending stars.
        key=lambda p: (p.archived, -p.stars, p.id),
    )


def rank_by_trending(plugins: list[LatestPlugin]) -> list[LatestPlugin]:
    return sorted(
        plugins,
        # Archived bottom; None delta below 0-delta; then descending delta;
        # tie-break by total stars desc; finally by id for stability.
        key=lambda p: (
            p.archived,
            p.stars_24h is None,
            -(p.stars_24h or 0),
            -p.stars,
            p.id,
        ),
    )
