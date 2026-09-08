from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECISIONS = REPO / "docs" / "decisions"


def test_adrs_exist_with_required_sections() -> None:
    expected = [
        "ADR-001-private-then-public.md",
        "ADR-002-scripted-turns-and-authorship.md",
        "ADR-003-judge-family-exclusion.md",
        "ADR-004-run-interface.md",
        "ADR-005-coder-families.md",
    ]
    for name in expected:
        text = (DECISIONS / name).read_text(encoding="utf-8")
        for section in ("## Context", "## Decision", "## Consequences"):
            assert section in text, f"{name} lacks {section}"


def test_construct_has_definition_origin_and_bibliography() -> None:
    text = (REPO / "docs" / "construct.md").read_text(encoding="utf-8")
    for heading in ("## Definition", "## Theoretical origin", "## Why this is new", "## Bibliography"):
        assert heading in text
    assert "paternalistic withholding" in text.lower()
    assert "sensitizing concept" in text


def test_method_and_rubric_prose_exist() -> None:
    method = (REPO / "docs" / "method.md").read_text(encoding="utf-8")
    assert "constant comparison" in method.lower() and "forcing" in method.lower()
    rubric = (REPO / "docs" / "rubric.md").read_text(encoding="utf-8")
    assert "S3" in rubric and "appropriate_referral" in rubric
    assert (REPO / "docs" / "sampling-log.md").is_file()
    assert (REPO / "docs" / "brief" / "kupuna-bench-brief.pdf").is_file()
