"""Source protocol and RawCandidate dataclass.

Each discovery source implements `Source` to yield `RawCandidate`s. Sources
emit only repo + source name + hint about target assistant(s). The
orchestrator fetches canonical star counts separately so multi-source hits
on the same repo only cost one API call."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RawCandidate:
    repo: str               # "owner/name"
    source: str             # adapter name (for dedupe attribution + logs)
    hint_assistants: list[str]


class Source(Protocol):
    name: str
    default_assistant: str

    def fetch_candidates(self) -> Iterable[RawCandidate]: ...
