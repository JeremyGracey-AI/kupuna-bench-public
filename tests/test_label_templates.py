import csv
import json
import re
from pathlib import Path

from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios
from scripts.make_label_templates import main as make_templates

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"


def _run_with_judge_errors(tmp_path: Path) -> Path:
    """Two models, three scenarios, two runs; the judge fails on every neutral hospice transcript."""
    scenarios = load_scenarios(FIXTURES)
    judge = ScriptedJudge(
        malformed_when=lambda s, t: s.id == "t1-hospice-enrollment" and t.variant == "neutral"
    )
    names = ("fake-a", "fake-b")
    models = [ScriptedChat(name, family=name, responder=lambda m: "A reply.") for name in names]
    result = run(scenarios, models=models, judge=judge, rubric=load_rubric(), runs=2, allow_draft=True)
    path = tmp_path / "run-2026-09-09-1.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path


def test_templates_are_blind_and_decodable(tmp_path: Path) -> None:
    result_json = _run_with_judge_errors(tmp_path)
    labels_dir = tmp_path / "labels"
    csv_paths, sheet_path, key_path = make_templates(
        result_json, ["melissa"], scenarios_dir=FIXTURES, out_dir=labels_dir, seed=3
    )
    key_map = json.loads(key_path.read_text(encoding="utf-8"))
    assert key_path.parent == tmp_path and not list(labels_dir.glob("KEY-*"))  # the map stays apart
    with csv_paths[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    items = {r["item"] for r in rows}
    assert items == set(key_map) and all(re.fullmatch(r"item-\d{2}", i) for i in items)
    assert all(r["severity"] == "" and r["direction"] == "" for r in rows)
    sheet = sheet_path.read_text(encoding="utf-8")
    for leaked in ("fake-a", "fake-b", "age_cue", "neutral", "|", "information_completeness", "run 1"):
        assert leaked not in sheet, leaked
    assert "I'm 84" in sheet  # the stimulus itself stays visible
    decoded = set(key_map.values())
    assert any(k.startswith("t1-hospice-enrollment|neutral|") for k in decoded)  # judge-error rows included
    assert len({k.rsplit("|", 1)[0] for k in decoded}) == 3 * 2 * 2  # one run per cell, every cell present
    assert list(key_map.values()) != sorted(key_map.values())  # presentation order is shuffled by seed


def test_answer_keys_are_in_the_sheet_by_default_and_optional(tmp_path: Path) -> None:
    result_json = _run_with_judge_errors(tmp_path)
    _, with_keys, _ = make_templates(result_json, ["m"], scenarios_dir=FIXTURES, out_dir=tmp_path / "a")
    _, without, _ = make_templates(
        result_json, ["m"], scenarios_dir=FIXTURES, out_dir=tmp_path / "b", with_keys=False
    )
    assert "answer key" in with_keys.read_text(encoding="utf-8").lower()
    assert "answer key" not in without.read_text(encoding="utf-8").lower()
