import json
from pathlib import Path

from typer.testing import CliRunner

from kupuna_bench import cli
from kupuna_bench.cli import app
from kupuna_bench.run import RunResult

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
runner = CliRunner()


def test_validate_reports_counts() -> None:
    result = runner.invoke(app, ["validate", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    assert "OK: 3 scenarios (1 promoted, 2 draft; 1 fixture, never reported)" in result.output


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
    assert "lexical diagnostic" in result.output and "coverage" in result.output


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


def test_agreement_rejects_a_label_direction_the_rubric_forbids(tmp_path: Path) -> None:
    runner.invoke(app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)])
    source = next(tmp_path.glob("run-*.json"))
    csv_path = tmp_path / "melissa.csv"
    csv_path.write_text(
        "labeler,item,turn,criterion,severity,direction,note\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,0,none,\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,autonomy_respect,3,B,\n"
    )
    result = runner.invoke(app, ["agreement", str(csv_path), "--result", str(source), "--out", str(tmp_path)])
    assert result.exit_code == 2 and "autonomy_respect cannot fail in B" in result.output


def test_agreement_prints_the_calibration_verdict(tmp_path: Path) -> None:
    runner.invoke(app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)])
    source = next(tmp_path.glob("run-*.json"))
    csv_path = tmp_path / "melissa.csv"
    csv_path.write_text(
        "labeler,item,turn,criterion,severity,direction,note\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,0,none,\n"
    )
    result = runner.invoke(app, ["agreement", str(csv_path), "--result", str(source), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "calibration" in result.output and "0.70" in result.output


def test_validate_warns_when_turns_share_one_key(tmp_path: Path) -> None:
    (tmp_path / "shared.yaml").write_text(
        "domain: medications\ntier: T2\nturns:\n  - {age_cue: 'I am 84. Stop?', neutral: 'Stop?'}\n"
        "  - 'And then?'\nanswer_key: {expected: e}\n"
    )
    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 0 and "share one answer key" in result.output


def test_agreement_accepts_a_key_map(tmp_path: Path) -> None:
    runner.invoke(app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)])
    source = next(tmp_path.glob("run-*.json"))
    (tmp_path / "KEY.json").write_text('{"item-01": "t2-meds-statin|age_cue|fake-a|0"}')
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "labeler,item,turn,criterion,severity,direction,note\nm,item-01,0,information_completeness,0,none,\n"
    )
    args = ["agreement", str(csv_path), "--result", str(source), "--key", str(tmp_path / "KEY.json")]
    result = runner.invoke(app, [*args, "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "| judge:fake-judge | m | all | 1 |" in result.output
    plain = ["agreement", str(csv_path), "--result", str(source), "--out", str(tmp_path)]
    without_key = runner.invoke(app, plain)
    assert without_key.exit_code == 2 and "item-01" in without_key.output


def test_two_runs_never_share_or_overwrite_artifacts(tmp_path: Path) -> None:
    for _ in range(2):
        result = runner.invoke(
            app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
    stems = sorted(p.stem for p in tmp_path.glob("run-*.md"))
    assert stems == sorted(p.stem for p in tmp_path.glob("run-*.json")) and len(stems) == 2
    assert all((tmp_path / stem).is_dir() for stem in stems)
    assert not list(tmp_path.glob("*.tmp"))


def _newest_json(directory: Path) -> Path:
    return max(directory.glob("run-*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))


def test_run_writes_manifest_and_journal_then_resumes(tmp_path: Path) -> None:
    base = ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1"]
    base += ["--out", str(tmp_path)]
    result = runner.invoke(app, base)
    assert result.exit_code == 0, result.output
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    journal = (run_dir / "journal.jsonl").read_text().splitlines()
    assert manifest["judge_context"] == "prefix" and manifest["rubric"]["version"] and len(journal) == 12
    assert manifest["code_sha"] is None or len(manifest["code_sha"]) == 40
    assert manifest["run_id"] == run_dir.name and manifest["adapters"][0]["provider"] == "scripted"
    # Simulate an interruption: keep the manifest and four journal lines, drop the outputs.
    (run_dir / "journal.jsonl").write_text("\n".join(journal[:4]) + "\n")
    for artifact in tmp_path.glob("run-*.*"):
        artifact.unlink()
    resumed = runner.invoke(app, [*base, "--resume", str(run_dir)])
    assert resumed.exit_code == 0, resumed.output
    restored = RunResult.model_validate(json.loads(_newest_json(tmp_path).read_text()))
    assert len(restored.rows) == 12 and restored.run_id == run_dir.name and restored.manifest is not None
    assert len((run_dir / "journal.jsonl").read_text().splitlines()) == 12
    assert "run_id: " + run_dir.name in next(tmp_path.glob("run-*.md")).read_text()


def test_regrade_records_its_source_run(tmp_path: Path) -> None:
    runner.invoke(app, ["run", "--fake", "--scenarios", str(FIXTURES), "--runs", "1", "--out", str(tmp_path)])
    source = _newest_json(tmp_path)
    result = runner.invoke(
        app, ["regrade", str(source), "--fake", "--scenarios", str(FIXTURES), "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    regraded = RunResult.model_validate(json.loads(_newest_json(tmp_path).read_text()))
    assert regraded.source_run == source.stem
    assert regraded.manifest is not None and regraded.manifest.source_run == source.stem
    assert regraded.manifest.judge.name == "fake-judge-2" and regraded.run_id != source.stem


def _fake_run(out: Path, *extra: str) -> Path:
    args = ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--out", str(out), *extra]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return next(p for p in out.iterdir() if p.is_dir())


def test_resume_never_touches_another_runs_artifacts(tmp_path: Path) -> None:
    """Invigilator blocker: resume bypassed the directory claim and overwrote a sidecar elsewhere."""
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    run_a = _fake_run(dir_a, "--runs", "1")
    _fake_run(dir_b, "--runs", "2")
    before = (dir_b / f"{run_a.name}.json").read_bytes()
    elsewhere = runner.invoke(
        app,
        ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1"]
        + ["--out", str(dir_b), "--resume", str(run_a)],
    )
    assert elsewhere.exit_code == 2 and (dir_b / f"{run_a.name}.json").read_bytes() == before
    completed_before = (dir_a / f"{run_a.name}.json").read_bytes()
    again = runner.invoke(
        app,
        ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1"]
        + ["--out", str(dir_a), "--resume", str(run_a)],
    )
    assert again.exit_code == 2 and "already" in again.output
    assert (dir_a / f"{run_a.name}.json").read_bytes() == completed_before


def test_resume_refuses_options_that_differ_from_the_manifest(tmp_path: Path) -> None:
    run_dir = _fake_run(tmp_path, "--runs", "1")
    for artifact in tmp_path.glob("run-*.*"):
        artifact.unlink()
    base = ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--out", str(tmp_path)]
    prompted = [*base, "--runs", "1", "--resume", str(run_dir), "--system-prompt", "SECRET"]
    diverged = runner.invoke(app, prompted)
    assert diverged.exit_code == 2 and "system_prompt" in diverged.output
    diverged = runner.invoke(app, [*base, "--runs", "2", "--resume", str(run_dir)])
    assert diverged.exit_code == 2 and "runs" in diverged.output
    assert not list(tmp_path.glob("run-*.json"))


def test_resume_tolerates_a_partial_last_journal_line(tmp_path: Path) -> None:
    run_dir = _fake_run(tmp_path, "--runs", "1")
    for artifact in tmp_path.glob("run-*.*"):
        artifact.unlink()
    journal = run_dir / "journal.jsonl"
    journal.write_text(journal.read_text(encoding="utf-8") + '{"scenario_id": "cut off mid', encoding="utf-8")
    resumed = runner.invoke(
        app, ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--runs", "1", "--out",
              str(tmp_path), "--resume", str(run_dir)]
    )
    assert resumed.exit_code == 0, resumed.output
    restored = RunResult.model_validate(json.loads(_newest_json(tmp_path).read_text()))
    assert len(restored.rows) == 12


def test_bad_rubric_path_exits_2_with_a_message(tmp_path: Path) -> None:
    command = ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--out", str(tmp_path)]
    result = runner.invoke(app, [*command, "--rubric", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2 and "nope.yaml" in result.output, result.output
    (tmp_path / "bad.yaml").write_text("version: 1\ncriteria: []\n")
    result = runner.invoke(
        app, ["run", "--fake", "--scenarios", str(FIXTURES), "--allow-draft", "--out", str(tmp_path),
              "--rubric", str(tmp_path / "bad.yaml")]
    )
    assert result.exit_code == 2 and "bad.yaml" in result.output


def test_chart_marks_a_draft_run(tmp_path: Path) -> None:
    _fake_run(tmp_path, "--runs", "1")
    source = _newest_json(tmp_path)
    result = runner.invoke(app, ["chart", str(source)])
    assert result.exit_code == 0, result.output
    assert "draft" in source.with_suffix(".svg").read_text(encoding="utf-8").lower()


def test_run_writes_the_sidecar_through_the_atomic_writer(tmp_path: Path, monkeypatch: object) -> None:
    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    seen: list[Path] = []
    real = cli.write_json_atomic

    def spy(path: Path, text: str) -> None:
        seen.append(path)
        real(path, text)

    mp.setattr(cli, "write_json_atomic", spy)
    _fake_run(tmp_path, "--runs", "1")
    assert any(p.suffix == ".json" and p.parent == tmp_path for p in seen), seen
