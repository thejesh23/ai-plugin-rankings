"""Generate stable kebab-case slug IDs for plugins.yaml entries.

The id is derived from the repo name only. Collisions are resolved by
prepending the owner; double collisions by appending a 4-char hash of the
full repo. Deterministic: same repo + same existing_ids always yields the
same id."""
from __future__ import annotations

import hashlib
import re


def generate_id(repo: str, existing_ids: set[str]) -> str:
    owner, name = repo.split("/")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if slug and slug not in existing_ids:
        return slug
    qualified = f"{owner.lower()}-{slug}" if slug else owner.lower()
    if qualified not in existing_ids:
        return qualified
    suffix = hashlib.sha1(repo.encode()).hexdigest()[:4]
    return f"{qualified}-{suffix}"
