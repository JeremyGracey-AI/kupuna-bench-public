import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from kupuna_bench.agreement import LABEL_COLUMNS, item_key
from kupuna_bench.cli import app
from kupuna_bench.run import RunResult
from scripts.make_label_templates import main as make_templates

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
runner = CliRunner()


def _build_fake_run(tmp_path: Path) -> Path:
    result = runner.invoke(
        app,
        [
            "run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "2",
            "--out", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    return next(tmp_path.glob("run-*.json"))


def test_label_templates_and_transcript_sheet(tmp_path: Path) -> None:
    result_json = _build_fake_run(tmp_path)
    run_result = RunResult.model_validate(json.loads(result_json.read_text(encoding="utf-8")))
    run0 = [r for r in run_result.rows if r.run_index == 0 and r.verdicts is not None]
    assert run0, "the fake run should produce graded run_index==0 rows"
    turns_per_item = {
        item_key(r.scenario_id, r.variant, r.model, r.run_index): len(r.verdicts.turns)
        for r in run0
        if r.verdicts is not None
    }

    labels_dir = tmp_path / "labels"
    csv_paths, sheet_path = make_templates(
        result_json, ["melissa", "jeremy"], scenarios_dir=FIXTURES, out_dir=labels_dir
    )

    assert {p.name for p in csv_paths} == {
        f"melissa-{result_json.stem}.csv",
        f"jeremy-{result_json.stem}.csv",
    }
    for path in csv_paths:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert tuple(reader.fieldnames or ()) == LABEL_COLUMNS
            rows = list(reader)
        assert rows
        counts: dict[str, int] = {}
        for row in rows:
            assert row["severity"] == "" and row["direction"] == ""
            assert not row["item"].endswith("|1"), "run_index 1 must be excluded"
            counts[row["item"]] = counts.get(row["item"], 0) + 1
        assert counts == {item: 5 * turns for item, turns in turns_per_item.items()}

    sheet_text = sheet_path.read_text(encoding="utf-8")
    assert sheet_path.name == f"TRANSCRIPTS-{result_json.stem}.md"
    for item in turns_per_item:
        assert item in sheet_text
    # No verdict data (rubric criterion ids, severities) leaks into the blind reading sheet.
    assert "information_completeness" not in sheet_text
    assert "autonomy_respect" not in sheet_text
