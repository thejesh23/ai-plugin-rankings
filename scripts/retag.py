"""Re-evaluate every entry in plugins.yaml against the current
resolve_assistants logic. Useful after the algorithm changes.

Not wired into any cron. Run manually after merging an algorithm change:
    GITHUB_TOKEN=$(gh auth token) python -m scripts.retag
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from ruamel.yaml import YAML

from scripts.discover import resolve_assistants
from scripts.github_api import GitHubClient, RateLimitError, RepoMissingError

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)

# Sleep between successive GitHub requests to stay under the secondary
# (abuse-detection) rate limit. 0.2s ≈ 5 req/s ≈ 18k/hr — well below the
# 5000/hr primary budget but slow enough that the secondary detector stays
# quiet.
_THROTTLE_SECONDS = 0.2

# Write a checkpoint to disk every N processed entries so a mid-loop crash
# (network blip, rate-limit hit on the next call) preserves the work done.
_CHECKPOINT_EVERY = 50


def retag_all(
    yaml_path: Path, gh: GitHubClient, throttle: float = _THROTTLE_SECONDS,
) -> int:
    """Re-evaluate assistants for every entry in plugins.yaml.

    Returns the number of entries updated. Throttles between API calls and
    checkpoints progress every N entries so a partial run preserves work."""
    with yaml_path.open("r", encoding="utf-8") as f:
        doc = _yaml.load(f)
    changed = 0
    for idx, entry in enumerate(doc["plugins"]):
        try:
            data = gh.fetch_repo(entry["repo"])
        except RepoMissingError:
            continue
        except RateLimitError:
            # Either a real rate limit OR a 403 from SAML SSO orgs (e.g.
            # microsoft/*). Skip this entry and continue — true rate limit
            # will keep tripping but at least we don't abort with progress
            # already made.
            continue
        if throttle:
            time.sleep(throttle)
        new = sorted(resolve_assistants(data, set(), readme=None))
        if new and list(entry["assistants"]) != new:
            entry["assistants"] = new
            changed += 1
        if changed and (idx + 1) % _CHECKPOINT_EVERY == 0:
            with yaml_path.open("w", encoding="utf-8") as f:
                _yaml.dump(doc, f)
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
