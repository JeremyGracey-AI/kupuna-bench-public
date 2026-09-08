import kupuna_bench


def test_version_is_semver() -> None:
    major, minor, patch = kupuna_bench.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
