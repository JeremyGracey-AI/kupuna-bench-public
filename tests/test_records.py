from datetime import date
from pathlib import Path

import pytest

from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.records import (
    allocate_run,
    facts_from_result,
    next_record_path,
    render_record,
    write_json_atomic,
    write_record,
)
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def _facts(verdict: str = "PASS", draft: bool = True, **extra: object) -> dict[str, object]:
    result = run(
        load_scenarios(FIXTURES), models=[ScriptedChat("a", family="a")], judge=ScriptedJudge(),
        rubric=RUBRIC, runs=1
    )
    facts = facts_from_result(
        result, gate_name="PLUMBING_GATE", verdict=verdict, shortfalls=[],
        timestamp="2026-09-08T10:00:00Z", driver="pytest", draft=draft,
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


def test_allocation_claims_a_directory_and_skips_orphan_json(tmp_path: Path) -> None:
    """Review finding 6: an orphan JSON from an interrupted write must never be overwritten."""
    day = date(2026, 9, 8)
    (tmp_path / "run-2026-09-08-1.json").write_text("{}")
    first = allocate_run(tmp_path, day)
    assert first.run_id == "run-2026-09-08-2" and first.dir.is_dir()
    assert first.record.name == "run-2026-09-08-2.md" and first.json_path.name == "run-2026-09-08-2.json"
    second = allocate_run(tmp_path, day)
    assert second.run_id == "run-2026-09-08-3"
    assert next_record_path(tmp_path, day).name == "run-2026-09-08-4.md"
    assert (tmp_path / "run-2026-09-08-1.json").read_text() == "{}"


def test_atomic_json_write_leaves_no_tmp(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    write_json_atomic(target, "{}")
    write_json_atomic(target, "{\"a\": 1}")
    assert target.read_text() == "{\"a\": 1}" and not list(tmp_path.glob("*.tmp"))


def test_record_front_matter_names_run_id_code_sha_and_manifest() -> None:
    manifest = "results/run-2026-09-08-1/manifest.json"
    facts = _facts(run_id="run-2026-09-08-1", code_sha="abc123", manifest=manifest)
    text = render_record(facts, "run-2026-09-08-1")
    assert "run_id: run-2026-09-08-1" in text and "code_sha: abc123" in text
    assert "manifest: results/run-2026-09-08-1/manifest.json" in text


def test_fixture_runs_are_always_draft() -> None:
    """reviewed_by: fixture is test provenance; no reporting path may treat such a run as reportable."""
    facts = _facts(draft=False)
    assert facts["draft"] is True
    assert any("never reported" in str(note) for note in facts["notes"])  # type: ignore[union-attr]
