"""Re-evaluate every entry in plugins.yaml against the current
resolve_assistants logic. Useful after the algorithm changes.

Not wired into any cron. Run manually after merging an algorithm change:
    GITHUB_TOKEN=$(gh auth token) python -m scripts.retag
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ruamel.yaml import YAML

from scripts.discover import resolve_assistants
from scripts.github_api import GitHubClient, RepoMissingError

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def retag_all(yaml_path: Path, gh: GitHubClient) -> int:
    """Re-evaluate assistants for every entry in plugins.yaml.

    Returns the number of entries updated. Does not write the file if
    nothing changed. Uses no source hints (hint history isn't persisted)."""
    with yaml_path.open("r", encoding="utf-8") as f:
        doc = _yaml.load(f)
    changed = 0
    for entry in doc["plugins"]:
        try:
            data = gh.fetch_repo(entry["repo"])
        except RepoMissingError:
            continue
        new = sorted(resolve_assistants(data, set(), readme=None))
        if new and list(entry["assistants"]) != new:
            entry["assistants"] = new
            changed += 1
    if changed:
        with yaml_path.open("w", encoding="utf-8") as f:
            _yaml.dump(doc, f)
    return changed


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)
    gh = GitHubClient(token=token)
    try:
        n = retag_all(Path("plugins.yaml"), gh)
    finally:
        gh.close()
    print(f"Updated {n} entries.")


if __name__ == "__main__":
    main()
