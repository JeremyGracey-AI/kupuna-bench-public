from pathlib import Path

import pytest

from kupuna_bench.agreement import (
    LABEL_COLUMNS,
    Label,
    agreement,
    cohen_kappa,
    item_key,
    judge_labels,
    load_labels,
    weighted_kappa,
)
from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def test_cohen_kappa_bounds_and_undefined() -> None:
    assert cohen_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
    assert cohen_kappa([0, 0, 0], [0, 0, 0]) is None  # no variation: undefined
    assert cohen_kappa([], []) is None
    low = cohen_kappa([0, 0, 1, 1], [1, 1, 0, 0])
    assert low is not None and low < 0


def test_weighted_kappa_rewards_near_misses() -> None:
    assert weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
    a = [0, 1, 2, 3, 0, 3]
    near = [0, 2, 2, 3, 1, 3]
    far = [3, 1, 2, 0, 0, 3]
    w_near, w_far = weighted_kappa(a, near), weighted_kappa(a, far)
    assert w_near is not None and w_far is not None and w_near > w_far
    plain_near = cohen_kappa(a, near)
    assert plain_near is not None and w_near > plain_near


def test_label_csv_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    path.write_text(
        ",".join(LABEL_COLUMNS) + "\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,2,A,"
        "withheld the deprescribing option\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,autonomy_respect,0,none,\n"
    )
    labels = load_labels([path])
    assert labels[0] == Label(
        labeler="melissa",
        item="t2-meds-statin|age_cue|fake-a|0",
        turn=0,
        criterion="information_completeness",
        severity=2,
        direction="A",
        note="withheld the deprescribing option",
    )
    assert item_key("t2-meds-statin", "age_cue", "fake-a", 0) == labels[0].item


def test_judge_labels_cover_every_verdict() -> None:
    result = run(
        load_scenarios(FIXTURES),
        models=[ScriptedChat("fake-a", family="a")],
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
    )
    labels = judge_labels(result)
    turns = sum(len(r.verdicts.turns) for r in result.rows if r.verdicts)
    assert len(labels) == turns * 5 and labels[0].labeler == "judge:scripted-judge"


def test_agreement_report_pairs_and_alignment() -> None:
    result = run(
        load_scenarios(FIXTURES),
        models=[ScriptedChat("fake-a", family="a")],
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
    )
    judge = judge_labels(result)
    melissa = [lbl.model_copy(update={"labeler": "melissa"}) for lbl in judge]
    jeremy = [
        lbl.model_copy(
            update={
                "labeler": "jeremy",
                "severity": 2 if lbl.criterion == "risk_flagging" else 0,
                "direction": "B" if lbl.criterion == "risk_flagging" else "none",
            }
        )
        for lbl in judge
    ]
    report = agreement(judge + melissa + jeremy)
    pairs = {(p.rater_a, p.rater_b, p.criterion): p for p in report.pairs}
    perfect = pairs[("judge:scripted-judge", "melissa", "all")]
    assert (
        perfect.n == len(judge)
        and perfect.exact_agreement == 1.0
        and perfect.kappa_severity_weighted is None
    )
    partial = pairs[("jeremy", "melissa", "all")]
    assert partial.exact_agreement < 1.0 and partial.kappa_passfail is not None
    assert ("jeremy", "melissa", "risk_flagging") in pairs
    assert "| jeremy | melissa | all |" in report.table()


def test_load_labels_rejects_blank_turn_or_severity(tmp_path: Path) -> None:
    # Blank severity cell
    path_blank_sev = tmp_path / "blank_severity.csv"
    path_blank_sev.write_text(
        ",".join(LABEL_COLUMNS) + "\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,0,information_completeness,,A,note\n"
    )
    with pytest.raises(ValueError, match="turn and severity are required integers"):
        load_labels([path_blank_sev])

    # Non-integer turn cell
    path_bad_turn = tmp_path / "bad_turn.csv"
    path_bad_turn.write_text(
        ",".join(LABEL_COLUMNS) + "\n"
        "melissa,t2-meds-statin|age_cue|fake-a|0,x,information_completeness,2,A,note\n"
    )
    with pytest.raises(ValueError, match="turn and severity are required integers"):
        load_labels([path_bad_turn])
