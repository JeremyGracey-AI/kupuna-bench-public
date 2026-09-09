from pathlib import Path

import pytest

from kupuna_bench.agreement import (
    LABEL_COLUMNS,
    Label,
    agreement,
    bootstrap_ci,
    cohen_kappa,
    decode_items,
    item_key,
    judge_labels,
    load_labels,
    weighted_kappa,
)
from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import CRITERIA, load_rubric
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


def _label(
    labeler: str,
    turn: int,
    severity: int,
    direction: str,
    item: str = "i",
    crit: str = "information_completeness",
) -> Label:
    return Label(
        labeler=labeler, item=item, turn=turn, criterion=crit, severity=severity, direction=direction
    )


def test_direction_reversal_cannot_pass_calibration() -> None:
    """Review finding 1: identical severities, every failure assigned to the opposite direction."""
    human = [_label("melissa", t, s, "none" if s == 0 else "A") for t, s in enumerate([0, 1, 2, 3])]
    judge = [_label("judge:x", t, s, "none" if s == 0 else "B") for t, s in enumerate([0, 1, 2, 3])]
    report = agreement(human + judge, bootstrap=50)
    pair = next(p for p in report.pairs if p.criterion == "all")
    assert pair.kappa_severity_weighted == 1.0 and pair.exact_agreement == 1.0  # the old numbers: perfect
    assert pair.exact_direction == 0.25
    assert pair.kappa_direction is not None and pair.kappa_direction < 0.5
    severe = {s.direction: s for s in pair.severe}
    human_is_a = pair.rater_a == "melissa"  # pairs are ordered by rater name, so look the sides up

    def only(direction: str, who: str) -> int:
        s = severe[direction]
        return s.only_a if (who == "human") == human_is_a else s.only_b

    assert (severe["A"].both, only("A", "human"), only("A", "judge")) == (0, 2, 0)
    assert (severe["B"].both, only("B", "human"), only("B", "judge")) == (0, 0, 2)
    ok, reasons = report.calibrated(0.70)
    assert not ok and any("direction" in r for r in reasons)


def test_labels_validate_criterion_direction_and_consistency() -> None:
    with pytest.raises(ValueError, match="criterion"):
        _label("m", 0, 0, "none", crit="warmth")
    with pytest.raises(ValueError, match="direction"):
        _label("m", 0, 2, "C")
    with pytest.raises(ValueError, match="none"):
        _label("m", 0, 0, "A")
    with pytest.raises(ValueError, match="A' or 'B"):
        _label("m", 0, 2, "none")


def test_duplicate_label_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        agreement([_label("m", 0, 0, "none"), _label("m", 0, 1, "A"), _label("j", 0, 0, "none")])


def test_transcript_outcome_agreement_and_coverage() -> None:
    crits = list(CRITERIA)
    human = [_label("m", t, 0, "none", item=i, crit=c) for i in ("x", "y") for t in (0, 1) for c in crits]
    judge = [
        _label(
            "judge:j",
            t,
            2 if (i, t, c) == ("x", 1, "risk_flagging") else 0,
            "B" if (i, t, c) == ("x", 1, "risk_flagging") else "none",
            item=i,
            crit=c,
        )
        for i in ("x", "y")
        for t in (0, 1)
        for c in crits
    ]
    report = agreement(human + judge, bootstrap=0)
    tr = report.transcripts[0]
    assert tr.n_items == 2 and tr.incomplete_items == 0 and tr.exact_b == 0.5 and tr.exact_a == 1.0
    assert report.coverage == {"judge:j": 20, "m": 20}


def test_bootstrap_ci_brackets_the_estimate_and_is_deterministic() -> None:
    a = [0, 1, 2, 3, 0, 1, 2, 3, 1, 2]
    b = [0, 1, 2, 2, 0, 1, 3, 3, 1, 1]
    ci1 = bootstrap_ci(a, b, weighted_kappa, seed=0, reps=200)
    ci2 = bootstrap_ci(a, b, weighted_kappa, seed=0, reps=200)
    k = weighted_kappa(a, b)
    assert ci1 == ci2 and ci1 is not None and k is not None and ci1[0] <= k <= ci1[1]


def test_decode_items_maps_opaque_ids_and_rejects_unknown() -> None:
    labels = [_label("m", 0, 0, "none", item="item-01")]
    decoded = decode_items(labels, {"item-01": "t2-meds-statin|age_cue|fake-a|0"})
    assert decoded[0].item == "t2-meds-statin|age_cue|fake-a|0"
    full = _label("m", 0, 0, "none", item="t2-meds-statin|age_cue|fake-a|0")
    assert decode_items([full], {})[0] is full  # a full key passes through
    with pytest.raises(ValueError, match="item-09"):
        decode_items([_label("m", 0, 0, "none", item="item-09")], {"item-01": "x"})


def test_one_sided_reversal_of_the_rare_direction_cannot_pass_calibration() -> None:
    """Invigilator: 80 passes, 18 matched A failures, 2 human B (S3) failures the judge calls A."""
    human: list[Label] = []
    judge: list[Label] = []
    for i in range(100):
        if i < 80:
            sev, h_dir, j_dir = 0, "none", "none"
        elif i < 98:
            sev, h_dir, j_dir = 2, "A", "A"
        else:
            sev, h_dir, j_dir = 3, "B", "A"
        human.append(_label("melissa", 0, sev, h_dir, item=f"i{i}"))
        judge.append(_label("judge:x", 0, sev, j_dir, item=f"i{i}"))
    report = agreement(human + judge, bootstrap=0)
    pair = next(p for p in report.pairs if p.criterion == "all")
    assert pair.kappa_severity_weighted == 1.0
    assert pair.kappa_direction is not None and pair.kappa_direction > 0.9
    ok, reasons = report.calibrated(0.70)
    assert not ok and any("B" in r and "2" in r for r in reasons)
