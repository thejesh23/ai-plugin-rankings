"""Surface plugins.yaml entries that don't look like real assistant plugins.

Not wired into any cron. Run manually after algorithm changes or when the
rankings start showing too much non-plugin noise:
    GITHUB_TOKEN=$(gh auth token) python -m scripts.purge

Output:
- purge-candidates.txt — one line per flagged entry (id, repo, description)
- console summary

Entries with ids in MANUAL_SEED_IDS are skipped (immune from flagging) so
the original curated seed list is never reported even if its descriptions
don't pass the plugin-signal heuristic.

The script DOES NOT modify plugins.yaml — humans decide what to remove
and open a PR. The risk of an algorithmic false-positive removing a legit
plugin is too high to automate.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from scripts.discover import MANUAL_SEED_IDS, is_plugin_signal
from scripts.github_api import GitHubClient, RateLimitError, RepoMissingError
from scripts.plugins_yaml import load_registry

_THROTTLE_SECONDS = 0.2  # same rationale as scripts/retag.py


def find_purge_candidates(
    plugins_yaml: Path, gh: GitHubClient, throttle: float = _THROTTLE_SECONDS,
) -> list[tuple[str, str, str]]:
    """Return list of (id, repo, description) for entries that look non-plugin."""
    registry = load_registry(plugins_yaml)
    candidates: list[tuple[str, str, str]] = []
    for entry in registry.plugins:
        if entry.id in MANUAL_SEED_IDS:
            continue
        try:
            data = gh.fetch_repo(entry.repo)
        except (RepoMissingError, RateLimitError):
            # Missing repos are flagged separately by the daily run; SAML 403s
            # masquerade as RateLimitError. Skip either way.
            continue
        if throttle:
            time.sleep(throttle)
        name = entry.repo.split("/")[-1]
        # No source attribution stored in plugins.yaml; check name/description
        # signals only. If neither passes, flag for human review.
        if not is_plugin_signal(name, data.description, source=""):
            candidates.append((entry.id, entry.repo, data.description[:120]))
    return candidates


def write_candidates_file(
    candidates: list[tuple[str, str, str]], path: Path,
) -> None:
    lines = [
        "# Purge candidates — entries flagged as non-plugins by is_plugin_signal.",
        "# Format: id  repo  description",
        "# Review each line, then delete the entry from plugins.yaml via PR.",
        "",
    ]
    for plugin_id, repo, desc in sorted(candidates):
        lines.append(f"{plugin_id}\t{repo}\t{desc}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)
    gh = GitHubClient(token=token)
    try:
        candidates = find_purge_candidates(Path("plugins.yaml"), gh)
    finally:
        gh.close()
    out_path = Path("purge-candidates.txt")
    write_candidates_file(candidates, out_path)
    print(f"Flagged {len(candidates)} entries. See {out_path}.")


if __name__ == "__main__":
    main()
