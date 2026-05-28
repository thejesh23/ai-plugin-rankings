"""Compute star deltas between two snapshots.

A None delta means we have no data for that comparison window (e.g. brand-new
plugin, or no snapshot from N days ago). The renderer displays None as "—",
distinguished from 0 (no change)."""
from collections.abc import Iterable

from scripts.models import SnapshotRow


def compute_delta(
    today: Iterable[SnapshotRow],
    previous: Iterable[SnapshotRow] | None,
) -> dict[str, int | None]:
    """Returns {plugin_id: stars_delta_or_None}."""
    if previous is None:
        return {r.id: None for r in today}
    prev_by_id = {r.id: r for r in previous}
    out: dict[str, int | None] = {}
    for r in today:
        prev = prev_by_id.get(r.id)
        out[r.id] = (r.stars - prev.stars) if prev is not None else None
    return out
