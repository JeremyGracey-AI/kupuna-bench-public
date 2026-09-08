from datetime import date
from pathlib import Path

import pytest

from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.records import facts_from_result, next_record_path, render_record, write_record
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def _facts(verdict: str = "PASS", **extra: object) -> dict[str, object]:
    result = run(
        load_scenarios(FIXTURES), models=[ScriptedChat("a", family="a")], judge=ScriptedJudge(),
        rubric=RUBRIC, runs=1
    )
    facts = facts_from_result(
        result, gate_name="PLUMBING_GATE", verdict=verdict, shortfalls=[],
        timestamp="2026-09-08T10:00:00Z", driver="pytest", draft=True,
    )
    facts.update(extra)
    return facts


def test_allocation_is_monotonic_and_never_refills(tmp_path: Path) -> None:
    day = date(2026, 9, 8)
    assert next_record_path(tmp_path, day).name == "run-2026-09-08-1.md"
    (tmp_path / "run-2026-09-08-3.md").write_text("x")
    assert next_record_path(tmp_path, day).name == "run-2026-09-08-4.md"


def test_render_has_frontmatter_metrics_and_draft_marker() -> None:
    text = render_record(_facts(), "run-2026-09-08-1")
    assert text.startswith("---\nrecord: run-2026-09-08-1\n")
    assert "system: kupuna-bench" in text and "draft: true" in text and "| well_formed |" in text
    assert "verdict: PASS" in text and "judge: scripted-judge" in text


def test_fail_must_name_shortfalls() -> None:
    with pytest.raises(ValueError, match="shortfalls"):
        render_record(_facts("FAIL"), "run-x")
    text = render_record(_facts("FAIL", shortfalls=["well_formed: 0.500 < required 1.000"]), "run-x")
    assert "## gate shortfalls (FAIL)" in text


def test_write_is_append_only(tmp_path: Path) -> None:
    first = write_record(_facts(), tmp_path, day=date(2026, 9, 8))
    second = write_record(_facts(), tmp_path, day=date(2026, 9, 8))
    assert (first.name, second.name) == ("run-2026-09-08-1.md", "run-2026-09-08-2.md")
    with pytest.raises(FileExistsError):
        write_record(_facts(), tmp_path, path=first)
