from scripts.id_gen import generate_id


def test_simple_slug() -> None:
    assert generate_id("obra/superpowers", set()) == "superpowers"


def test_lowercase_and_hyphens() -> None:
    assert generate_id("Some/Cool_Tool.Name", set()) == "cool-tool-name"


def test_collision_appends_owner() -> None:
    assert generate_id("alice/utils", {"utils"}) == "alice-utils"


def test_double_collision_appends_hash() -> None:
    out = generate_id("alice/utils", {"utils", "alice-utils"})
    assert out.startswith("alice-utils-")
    assert len(out) == len("alice-utils-") + 4


def test_deterministic_across_calls() -> None:
    a = generate_id("alice/utils", {"utils", "alice-utils"})
    b = generate_id("alice/utils", {"utils", "alice-utils"})
    assert a == b


def test_handles_dots_and_underscores() -> None:
    assert generate_id("org/my.cool_thing", set()) == "my-cool-thing"
