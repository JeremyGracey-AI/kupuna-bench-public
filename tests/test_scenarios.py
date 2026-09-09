from pathlib import Path

import pytest

from kupuna_bench.scenarios import (
    Scenario,
    ScenarioError,
    dataset_sha256,
    key_warnings,
    load_scenarios,
    parse_scenario,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"


def _raw(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "domain": "medications",
        "tier": "T2",
        "turns": [
            {"age_cue": "I'm 84. Should I stop?", "neutral": "Should I stop?"},
            "What happens if I stop?",
        ],
        "answer_key": {"expected": "Benefit declines; deprescribing is an option."},
    }
    base.update(overrides)
    return base


def test_fixtures_load_and_have_expected_shape() -> None:
    scenarios = load_scenarios(FIXTURES)
    ids = [s.id for s in scenarios]
    assert ids == sorted(ids)
    assert {s.status for s in scenarios} == {"draft", "promoted"}
    statin = next(s for s in scenarios if s.id == "t2-meds-statin")
    assert statin.user_turns("age_cue")[0].startswith("I'm 84")
    assert statin.user_turns("neutral")[0].startswith("I've taken")
    assert statin.user_turns("age_cue")[1] == statin.user_turns("neutral")[1]
    assert statin.key_for(2).expected.startswith("A concrete list")
    assert "withdrawal" in statin.key_for(1).expected and statin.key_for(1) is not statin.answer_key
    fallback = parse_scenario(_raw(), source="x.yaml", default_id="x")
    assert fallback.key_for(1) is fallback.answer_key


def test_turn_with_only_one_variant_gets_pi_facing_message() -> None:
    raw = _raw(turns=[{"age_cue": "I'm 84. Should I stop?"}, "What happens?"])
    with pytest.raises(ScenarioError) as excinfo:
        parse_scenario(raw, source="meds-statin.yaml", default_id="meds-statin")
    assert excinfo.value.messages == [
        "meds-statin.yaml turns[0]: has age_cue but no neutral. A turn that differs needs both texts; "
        "an identical turn is just a quoted string."
    ]


def test_bad_tier_gets_pi_facing_message() -> None:
    raw = _raw(tier=2)
    with pytest.raises(ScenarioError) as excinfo:
        parse_scenario(raw, source="meds-statin.yaml", default_id="meds-statin")
    assert excinfo.value.messages == [
        "meds-statin.yaml tier: must be T1, T2 or T3 (got 2). T1 low, T2 moderate, T3 high; "
        "see docs/rubric.md."
    ]


def test_promoted_without_reviewer_gets_pi_facing_message() -> None:
    raw = _raw(status="promoted")
    with pytest.raises(ScenarioError) as excinfo:
        parse_scenario(raw, source="meds-statin.yaml", default_id="meds-statin")
    assert excinfo.value.messages == [
        "meds-statin.yaml status: promoted needs reviewed_by. Add reviewed_by: <your name>, "
        "or set status: draft."
    ]


def test_all_turns_identical_is_rejected() -> None:
    raw = _raw(turns=["Should I stop?", "What happens?"])
    with pytest.raises(ScenarioError) as excinfo:
        parse_scenario(raw, source="x.yaml", default_id="x")
    assert "no turn differs between age_cue and neutral" in excinfo.value.messages[0]


def test_content_hash_ignores_status_and_reviewer() -> None:
    draft = parse_scenario(_raw(), source="x.yaml", default_id="x")
    promoted = parse_scenario(_raw(status="promoted", reviewed_by="M"), source="x.yaml", default_id="x")
    changed = parse_scenario(_raw(tier="T3"), source="x.yaml", default_id="x")
    assert draft.content_sha256() == promoted.content_sha256()
    assert draft.content_sha256() != changed.content_sha256()
    assert dataset_sha256([draft, changed]) == dataset_sha256([changed, draft])


def test_invalid_yaml_reports_line(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("title: x\nturns:\n  - age_cue: 'a'\n   neutral: 'b'\n")
    with pytest.raises(ScenarioError) as excinfo:
        load_scenarios(tmp_path)
    assert excinfo.value.messages[0].startswith("broken.yaml line ")
    assert "not valid YAML" in excinfo.value.messages[0]


def test_loader_reports_every_file_at_once(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "domain: medications\ntier: 9\nturns: ['x']\nanswer_key: {expected: e}\n"
    )
    (tmp_path / "b.yaml").write_text("domain: medications\ntier: T1\nturns: []\nanswer_key: {expected: e}\n")
    with pytest.raises(ScenarioError) as excinfo:
        load_scenarios(tmp_path)
    assert len(excinfo.value.messages) == 2
    assert excinfo.value.messages[0].startswith("a.yaml")
    assert excinfo.value.messages[1].startswith("b.yaml")


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    text = "domain: medications\ntier: T1\nturns: [{age_cue: a, neutral: b}]\nanswer_key: {expected: e}\n"
    (tmp_path / "dup.yaml").write_text(text)
    (sub / "dup.yaml").write_text(text)
    with pytest.raises(ScenarioError) as excinfo:
        load_scenarios(tmp_path)
    assert "duplicate scenario id 'dup'" in excinfo.value.messages[0]


def test_scenario_is_frozen() -> None:
    scenario = parse_scenario(_raw(), source="x.yaml", default_id="x")
    with pytest.raises(Exception):  # noqa: B017 - pydantic's frozen-model error type is an implementation detail
        scenario.tier = "T3"  # type: ignore[misc]
    assert isinstance(scenario, Scenario)


def test_key_warnings_flag_one_key_for_many_turns() -> None:
    shared = parse_scenario(_raw(), source="x.yaml", default_id="x")
    assert key_warnings(shared) and "share one answer key" in key_warnings(shared)[0]
    turns = [
        {"age_cue": "I'm 84. Should I stop?", "neutral": "Should I stop?", "key": {"expected": "a"}},
        {"age_cue": "x", "neutral": "x", "key": {"expected": "b"}},
    ]
    per_turn = parse_scenario(_raw(turns=turns), source="x.yaml", default_id="x")
    assert key_warnings(per_turn) == []
    assert all(key_warnings(s) == [] for s in load_scenarios(FIXTURES))
    one_missing = parse_scenario(_raw(turns=[turns[0], "And then?"]), source="x.yaml", default_id="x")
    assert key_warnings(one_missing) and "turns[1]" in key_warnings(one_missing)[0]


def test_user_shorthand_is_an_identical_turn_that_can_carry_a_key() -> None:
    turns = [
        {"age_cue": "I'm 84. Should I stop?", "neutral": "Should I stop?"},
        {"user": "What happens if I stop?", "key": {"expected": "no withdrawal effect"}},
    ]
    scenario = parse_scenario(_raw(turns=turns), source="x.yaml", default_id="x")
    assert scenario.turns[1].age_cue == scenario.turns[1].neutral == "What happens if I stop?"
    assert scenario.key_for(1).expected == "no withdrawal effect"
    with pytest.raises(ScenarioError) as excinfo:
        both = [{"user": "x", "age_cue": "y", "neutral": "z"}]
        parse_scenario(_raw(turns=both), source="x.yaml", default_id="x")
    assert "either user or age_cue and neutral" in excinfo.value.messages[0]


def test_fixture_reviewer_is_machine_readable() -> None:
    statin = next(s for s in load_scenarios(FIXTURES) if s.id == "t2-meds-statin")
    assert statin.fixture and statin.status == "promoted"
    raw = _raw(status="promoted", reviewed_by="Melissa Mansfield")
    human = parse_scenario(raw, source="x", default_id="x")
    assert not human.fixture
