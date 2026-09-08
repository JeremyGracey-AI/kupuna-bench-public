import json
from pathlib import Path

from typer.testing import CliRunner

from kupuna_bench.cli import app
from kupuna_bench.run import RunResult

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
runner = CliRunner()


def test_validate_reports_counts() -> None:
    result = runner.invoke(app, ["validate", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    assert "OK: 3 scenarios (1 promoted, 2 draft)" in result.output


def test_validate_exits_2_with_messages(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "domain: medications\ntier: 7\nturns: ['x']\nanswer_key: {expected: e}\n"
    )
    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 2
    assert "bad.yaml tier: must be T1, T2 or T3 (got 7)" in result.output


def test_run_fake_writes_record_and_json(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1", "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    records = sorted(tmp_path.glob("run-*.md"))
    jsons = sorted(tmp_path.glob("run-*.json"))
    assert len(records) == 1 and len(jsons) == 1 and records[0].stem == jsons[0].stem
    text = records[0].read_text()
    assert "verdict: PASS" in text and "draft: true" in text and "gate: PLUMBING_GATE" in text
    restored = RunResult.model_validate(json.loads(jsons[0].read_text()))
    assert len(restored.rows) == 3 * 2 * 2 * 1
    assert "| fake-a | T2 | age_cue |" in result.output


def test_run_fake_without_allow_draft_runs_only_promoted(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    restored = RunResult.model_validate(json.loads(next(tmp_path.glob("run-*.json")).read_text()))
    assert {r.scenario_id for r in restored.rows} == {"t2-meds-statin"} and restored.skipped_draft == 2


def test_regrade_fake_writes_new_record(tmp_path: Path) -> None:
    runner.invoke(app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)])
    source = next(tmp_path.glob("run-*.json"))
    result = runner.invoke(
        app,
        ["regrade", str(source), "--fake", "--scenarios", str(FIXTURES), "--out", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert len(list(tmp_path.glob("run-*.json"))) == 2


def test_run_without_keys_fails_clearly(tmp_path: Path, monkeypatch: object) -> None:
    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    mp.delenv("OPENROUTER_API_KEY", raising=False)
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    mp.chdir(tmp_path)
    result = runner.invoke(
        app, ["run", "--scenarios", str(FIXTURES), "--allow-draft", "--out", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "OPENROUTER_API_KEY" in result.output


def test_regrade_missing_result_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "regrade", str(tmp_path / "nonexistent.json"), "--fake", "--scenarios", str(FIXTURES),
            "--out", str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "cannot load" in result.output


def test_run_fake_with_invalid_golden_exits_2(tmp_path: Path, monkeypatch: object) -> None:
    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    mp.chdir(tmp_path)
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "kupuna_golden.json").write_text(
        '{"_meta": {"promoted": true, "thresholds": {"ndcg": 1.0}}}'
    )
    result = runner.invoke(
        app,
        [
            "run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1", "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "golden file is invalid" in result.output


def test_code_fake_writes_coding_and_memos(tmp_path: Path, monkeypatch: object) -> None:
    import os

    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    runner.invoke(
        app,
        [
            "run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1", "--out",
            str(tmp_path),
        ],
    )
    source = next(tmp_path.glob("run-*.json"))
    mp.chdir(tmp_path)  # memos land under <cwd>/docs/memos
    result = runner.invoke(app, ["code", str(source), "--fake", "--orders", "2", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{source.stem}-coding.json").is_file()
    assert list((tmp_path / "docs" / "memos").glob("*-ai-coding-*.md"))
    assert "theory vocabulary in categories" in result.output and os.path.isdir(tmp_path / "docs")


def test_agreement_command(tmp_path: Path) -> None:
    runner.invoke(
        app,
        [
            "run",
            "--fake",
            "--scenarios",
            str(FIXTURES),
            "--runs",
            "1",
            "--out",
            str(tmp_path),
        ],
    )
    source = next(tmp_path.glob("run-*.json"))
    csv_path = tmp_path / "melissa.csv"
    csv_path.write_text(
        "labeler,item,turn,criterion,severity,direction,note\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,0,none,\n"
    )
    result = runner.invoke(
        app,
        [
            "agreement",
            str(csv_path),
            "--result",
            str(source),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "| judge:fake-judge | melissa | all |" in result.output and (
        tmp_path / f"{source.stem}-agreement.json"
    ).is_file()


def test_agreement_rejects_bad_csv(tmp_path: Path) -> None:
    runner.invoke(
        app,
        [
            "run",
            "--fake",
            "--scenarios",
            str(FIXTURES),
            "--runs",
            "1",
            "--out",
            str(tmp_path),
        ],
    )
    source = next(tmp_path.glob("run-*.json"))
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "labeler,item,turn,criterion,severity,direction,note\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,,none,\n"
    )
    result = runner.invoke(
        app,
        [
            "agreement",
            str(csv_path),
            "--result",
            str(source),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "turn and severity are required integers" in result.output


def test_chart_command(tmp_path: Path) -> None:
    runner.invoke(
        app,
        [
            "run",
            "--fake",
            "--scenarios",
            str(FIXTURES),
            "--allow-draft",
            "--runs",
            "1",
            "--out",
            str(tmp_path),
        ],
    )
    source = next(tmp_path.glob("run-*.json"))
    result = runner.invoke(app, ["chart", str(source)])
    assert result.exit_code == 0, result.output
    assert source.with_suffix(".svg").read_text().startswith("<svg")
