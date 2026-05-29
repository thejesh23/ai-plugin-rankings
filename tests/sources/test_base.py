from scripts.sources.base import RawCandidate


def test_raw_candidate_is_frozen_dataclass() -> None:
    c = RawCandidate(
        repo="obra/superpowers",
        source="github_topic_search",
        hint_assistants=["claude-code"],
    )
    assert c.repo == "obra/superpowers"
    assert c.source == "github_topic_search"
    assert c.hint_assistants == ["claude-code"]


def test_raw_candidate_equality() -> None:
    a = RawCandidate(repo="o/x", source="s", hint_assistants=["claude-code"])
    b = RawCandidate(repo="o/x", source="s", hint_assistants=["claude-code"])
    assert a == b
