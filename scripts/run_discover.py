"""Run discovery and open a PR with candidates.

Called by the weekly-discover workflow. Reads plugins.yaml to build the
known-repos set, runs find_candidates, writes a markdown PR body, and
exits. The workflow itself uses the body to open the PR."""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.discover import QUERY_TO_ASSISTANT, find_candidates, render_candidate_pr_body
from scripts.plugins_yaml import load_registry


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN required\n")
        sys.exit(2)

    registry = load_registry(Path("plugins.yaml"))
    known = {p.repo for p in registry.plugins}
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    candidates = find_candidates(
        token=token,
        queries=list(QUERY_TO_ASSISTANT.keys()),
        known_repos=known,
        min_stars=10,
        max_age_days=365,
        today=today,
    )

    body = render_candidate_pr_body(candidates)
    Path("candidates-body.md").write_text(body)
    print("has_candidates=" + ("true" if candidates else "false"))


if __name__ == "__main__":
    main()
