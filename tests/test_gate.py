from pathlib import Path

import pytest

from kupuna_bench.chat import ScriptedChat
from kupuna_bench.gate import PLUMBING_GATE, Gate, check_gate, gate_metrics, load_gate_from_meta
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def test_plumbing_gate_passes_on_clean_fake_run() -> None:
    scenarios = load_scenarios(FIXTURES)
    result = run(
        scenarios, models=[ScriptedChat("a", family="a")], judge=ScriptedJudge(),
        rubric=RUBRIC, runs=1, allow_draft=True
    )
    metrics = gate_metrics(result, n_scenarios=len(scenarios))
    assert metrics == {"well_formed": 1.0, "coverage": 1.0}
    ok, shortfalls = check_gate(metrics, PLUMBING_GATE)
    assert ok and shortfalls == []


def test_gate_names_shortfalls() -> None:
    scenarios = load_scenarios(FIXTURES)
    judge = ScriptedJudge(malformed_for=frozenset({"t2-meds-statin"}))
    result = run(
        scenarios, models=[ScriptedChat("a", family="a")], judge=judge, rubric=RUBRIC, runs=1
    )
    metrics = gate_metrics(result, n_scenarios=1)
    ok, shortfalls = check_gate(metrics, PLUMBING_GATE)
    assert not ok and shortfalls == ["well_formed: 0.000 < required 1.000"]


def test_gate_from_meta_requires_known_fields() -> None:
    assert load_gate_from_meta({"thresholds": {"well_formed": 0.9, "coverage": 1.0}}) == Gate(
        well_formed=0.9, coverage=1.0
    )
    with pytest.raises(ValueError, match="thresholds"):
        load_gate_from_meta({})
    with pytest.raises(ValueError, match="unknown"):
        load_gate_from_meta({"thresholds": {"ndcg": 1.0}})
