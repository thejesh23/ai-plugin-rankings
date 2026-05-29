"""Render latest.json + metadata into markdown files.

Deterministic: same input → same bytes. No timestamps in per-ranking files;
the README does carry generated_at since freshness is a user-facing signal."""
from __future__ import annotations

from dataclasses import dataclass

from scripts.models import LatestJson, LatestPlugin, MetadataEntry
from scripts.rank import rank_by_stars, rank_by_trending

ASSISTANT_LABELS: dict[str, str] = {
    "claude-code": "Claude Code",
    "cursor": "Cursor",
    "copilot": "GitHub Copilot",
    "codex": "Codex CLI",
}

TOP_N = 20
DASH = "—"


@dataclass(frozen=True)
class RenderOutput:
    readme: str
    rankings: dict[str, str]


def _row(p: LatestPlugin, rank: int, meta: dict[str, MetadataEntry]) -> str:
    md = meta.get(p.id)
    if md:
        desc = md.description
    elif p.description:
        # Fallback to GitHub's repo description; truncate so tables stay readable.
        # Escape pipe characters that would break Markdown table cell boundaries.
        desc = p.description[:100].replace("|", "\\|")
        if len(p.description) > 100:
            desc = desc.rstrip() + "…"
    else:
        desc = DASH
    cat = md.category if md else DASH
    assistants = ", ".join(ASSISTANT_LABELS[a] for a in p.assistants)
    stars = f"{p.stars:,}"
    d24 = DASH if p.stars_24h is None else f"{p.stars_24h:+,}"
    d7 = DASH if p.stars_7d is None else f"{p.stars_7d:+,}"
    name = f"[{p.id}]({p.url})"
    if p.archived:
        name = f"~~{name}~~"
    return f"| {rank} | {name} | {desc} | {assistants} | {stars} | {d24} | {d7} | {cat} |"


def _table(plugins: list[LatestPlugin], meta: dict[str, MetadataEntry]) -> str:
    header = "| Rank | Plugin | Description | Assistants | Stars | 24h | 7d | Category |\n"
    sep = "|---:|---|---|---|---:|---:|---:|---|\n"
    if not plugins:
        body = "| — | — | — | — | — | — | — | — |"
    else:
        body = "\n".join(_row(p, i + 1, meta) for i, p in enumerate(plugins))
    return header + sep + body + "\n"


def _per_assistant_file(
    assistant: str, plugins: list[LatestPlugin], meta: dict[str, MetadataEntry],
) -> str:
    filtered = [p for p in plugins if assistant in p.assistants]
    trending = rank_by_trending(filtered)
    all_time = rank_by_stars(filtered)
    label = ASSISTANT_LABELS[assistant]
    parts = [
        f"# {label} plugins\n",
        f"{len(filtered)} plugin(s). Trending sort uses 24h star delta.\n",
        "## Trending (24h)\n",
        _table(trending, meta),
        "## All-time (stars)\n",
        _table(all_time, meta),
    ]
    return "\n".join(parts)


def _readme(latest: LatestJson, meta: dict[str, MetadataEntry]) -> str:
    trending = rank_by_trending(latest.plugins)[:TOP_N]
    all_time = rank_by_stars(latest.plugins)[:TOP_N]
    counts = {a: sum(1 for p in latest.plugins if a in p.assistants)
              for a in ASSISTANT_LABELS}
    by_assistant = "\n".join(
        f"- [{ASSISTANT_LABELS[a]}](rankings/{a}.md) — {counts[a]} plugins"
        for a in ASSISTANT_LABELS
    )
    return "\n".join([
        "# AI Coding Assistant Plugin Rankings\n",
        f"Updated {latest.generated_at}. Source data in `data/`, history in `data` branch.\n",
        f"## Top {TOP_N} trending (24h)\n",
        _table(trending, meta),
        f"## Top {TOP_N} all-time (stars)\n",
        _table(all_time, meta),
        "## By assistant\n",
        by_assistant + "\n",
        "## Submit a plugin\n",
        "Open a PR adding an entry to `plugins.yaml`.\n",
    ])


def render_all(latest: LatestJson, meta: dict[str, MetadataEntry]) -> RenderOutput:
    rankings = {
        "all": "# All plugins by stars\n\n" + _table(rank_by_stars(latest.plugins), meta),
        "trending": "# All plugins by 24h trending\n\n" + _table(
            rank_by_trending(latest.plugins), meta),
    }
    for a in ASSISTANT_LABELS:
        rankings[a] = _per_assistant_file(a, latest.plugins, meta)
    return RenderOutput(readme=_readme(latest, meta), rankings=rankings)
