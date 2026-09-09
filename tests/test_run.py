import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from kupuna_bench.chat import Message, Reply, ScriptedChat, Usage
from kupuna_bench.judge import LLMJudge, ScriptedJudge, Transcript
from kupuna_bench.manifest import AdapterSpec
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import (
    DatasetMismatch,
    JudgeFamilyConflict,
    NothingToRun,
    Row,
    RunResult,
    expected_cells,
    regrade,
    run,
)
from kupuna_bench.scenarios import Scenario, load_scenarios, parse_scenario

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def _models() -> list[ScriptedChat]:
    return [ScriptedChat("fake-a", family="fake-a"), ScriptedChat("fake-b", family="fake-b")]


def _judge(**kwargs: object) -> ScriptedJudge:
    return ScriptedJudge("fake-judge", family="fake-judge", **kwargs)  # type: ignore[arg-type]


def test_only_promoted_scenarios_run_by_default() -> None:
    scenarios = load_scenarios(FIXTURES)
    result = run(scenarios, models=_models(), judge=_judge(), rubric=RUBRIC, runs=2)
    assert {row.scenario_id for row in result.rows} == {"t2-meds-statin"}
    assert len(result.rows) == expected_cells(1, 2, 2) == 1 * 2 * 2 * 2
    assert result.skipped_draft == 2 and result.allow_draft is False
    assert all(row.status == "promoted" for row in result.rows)


def test_allow_draft_runs_everything_and_is_deterministic() -> None:
    scenarios = load_scenarios(FIXTURES)
    first = run(scenarios, models=_models(), judge=_judge(), rubric=RUBRIC, runs=2, allow_draft=True)
    second = run(scenarios, models=_models(), judge=_judge(), rubric=RUBRIC, runs=2, allow_draft=True)
    assert first == second
    assert len(first.rows) == expected_cells(3, 2, 2)
    keys = [(r.scenario_id, r.variant, r.model, r.run_index) for r in first.rows]
    assert keys == sorted(keys)
    assert all(row.score is not None and row.score.outcome == "OK" for row in first.rows)
    assert first.summary().well_formed() == 1.0
    assert first.chat_spend_usd == 0.0
    assert first.judge_spend_usd == 0.0
    assert first.spend_usd == 0.0


def test_chat_failure_becomes_row_and_skips_judge() -> None:
    scenarios = load_scenarios(FIXTURES)

    def fail_when(messages: Sequence[Message]) -> str | None:
        user_turns = [m for m in messages if m["role"] == "user"]
        return "HTTP 503: down" if len(user_turns) == 2 and "84" in user_turns[0]["content"] else None

    flaky = ScriptedChat("flaky", family="fake-a", fail_when=fail_when)
    result = run(scenarios, models=[flaky], judge=_judge(), rubric=RUBRIC, runs=1)
    failed = [r for r in result.rows if r.error is not None]
    assert len(failed) == 1
    row = failed[0]
    assert row.variant == "age_cue" and row.error is not None
    assert row.error.stage == "chat" and row.error.turn == 1 and row.error.message == "HTTP 503: down"
    assert row.transcript.turns == 1 and row.verdicts is None and row.score is None
    assert result.summary().errors == {"chat": 1}


def test_malformed_judge_becomes_row_and_keeps_transcript() -> None:
    scenarios = load_scenarios(FIXTURES)
    judge = _judge(malformed_for=frozenset({"t2-meds-statin"}))
    result = run(scenarios, models=_models()[:1], judge=judge, rubric=RUBRIC, runs=1)
    assert all(r.error is not None and r.error.stage == "judge" for r in result.rows)
    assert all(r.transcript.turns == 3 for r in result.rows)
    assert all("malformed" in (r.error.message if r.error else "") for r in result.rows)


def test_same_family_judge_is_refused_before_any_call() -> None:
    scenarios = load_scenarios(FIXTURES)
    calls: list[int] = []
    chat = ScriptedChat("m", family="anthropic", responder=lambda m: calls.append(1) or "x")
    with pytest.raises(JudgeFamilyConflict, match="anthropic"):
        run(
            scenarios,
            models=[chat],
            judge=ScriptedJudge("j", family="anthropic"),
            rubric=RUBRIC,
            runs=1,
            allow_draft=True,
        )
    assert calls == []


def test_nothing_to_run_names_the_reason() -> None:
    scenarios = [s for s in load_scenarios(FIXTURES) if s.status == "draft"]
    with pytest.raises(NothingToRun, match="allow_draft"):
        run(scenarios, models=_models(), judge=_judge(), rubric=RUBRIC)
    with pytest.raises(NothingToRun, match="no models"):
        run(load_scenarios(FIXTURES), models=[], judge=_judge(), rubric=RUBRIC)
    with pytest.raises(ValueError, match="runs"):
        run(load_scenarios(FIXTURES), models=_models(), judge=_judge(), rubric=RUBRIC, runs=0)


def test_on_row_streams_every_row() -> None:
    seen: list[Row] = []
    result = run(
        load_scenarios(FIXTURES), models=_models(), judge=_judge(), rubric=RUBRIC, runs=1, on_row=seen.append
    )
    assert sorted(r.model_dump_json() for r in seen) == sorted(r.model_dump_json() for r in result.rows)


class _CostlyChat:
    name = "costly"
    family = "costly"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
        self.calls += 1
        return Reply(ok=True, text="ok", usage=Usage(input_tokens=1, output_tokens=1, cost_usd=1.0))


def test_spend_cap_marks_remaining_cells_without_calls() -> None:
    scenarios = load_scenarios(FIXTURES)
    costly = _CostlyChat()
    result = run(scenarios, models=[costly], judge=_judge(), rubric=RUBRIC, runs=3, spend_cap_usd=4.0)
    capped = [r for r in result.rows if r.error is not None and r.error.stage == "spend_cap"]
    completed = [r for r in result.rows if r.error is None]
    assert completed and capped and len(completed) + len(capped) == len(result.rows)
    assert result.spend_usd is not None and result.spend_usd >= 4.0
    assert costly.calls == 3 * len(completed)


def test_summary_cells_and_age_cue_delta() -> None:
    scenarios = load_scenarios(FIXTURES)

    def severity(scenario: Scenario, transcript: Transcript, turn: int, criterion: str) -> tuple[int, str]:
        return (
            (2, "A")
            if transcript.variant == "age_cue" and criterion == "information_completeness"
            else (0, "none")
        )

    result = run(scenarios, models=_models()[:1], judge=_judge(severity=severity), rubric=RUBRIC, runs=2)
    summary = result.summary()
    by_variant = {c.variant: c for c in summary.cells if c.model == "fake-a" and c.tier == "T2"}
    assert by_variant["age_cue"].rate_a == 1.0 and by_variant["neutral"].rate_a == 0.0
    delta = next(d for d in summary.age_cue_delta if d.model == "fake-a" and d.tier == "T2")
    assert delta.delta_a == 1.0 and delta.delta_b == 0.0
    assert "fake-a" in summary.table()


def test_regrade_keeps_transcripts_and_detects_dataset_mismatch() -> None:
    scenarios = load_scenarios(FIXTURES)
    result = run(scenarios, models=_models(), judge=_judge(), rubric=RUBRIC, runs=1, allow_draft=True)
    stricter = _judge(severity=lambda s, t, i, c: (2, "A") if c == "autonomy_respect" else (0, "none"))
    stricter.name = "stricter"
    again = regrade(result, scenarios, stricter, rubric=RUBRIC)
    assert [r.transcript for r in again.rows] == [r.transcript for r in result.rows]
    assert again.judge.name == "stricter"
    assert all(r.score and r.score.outcome == "OVERREFUSAL" for r in again.rows)
    changed = [
        parse_scenario({**s.model_dump(mode="json"), "tier": "T3"}, source="x", default_id=s.id)
        if s.id == "t2-meds-statin"
        else s
        for s in scenarios
    ]
    with pytest.raises(DatasetMismatch, match="t2-meds-statin"):
        regrade(result, changed, stricter, rubric=RUBRIC)
    with pytest.raises(JudgeFamilyConflict):
        regrade(result, scenarios, ScriptedJudge("j", family="fake-a"), rubric=RUBRIC)


def test_regrade_keeps_chat_failed_rows_verbatim() -> None:
    scenarios = load_scenarios(FIXTURES)

    def fail_when(messages: Sequence[Message]) -> str | None:
        user_turns = [m for m in messages if m["role"] == "user"]
        return "HTTP 503: down" if len(user_turns) == 2 and "84" in user_turns[0]["content"] else None

    flaky = ScriptedChat("flaky", family="fake-a", fail_when=fail_when)
    healthy = ScriptedChat("healthy", family="fake-b")
    result = run(scenarios, models=[flaky, healthy], judge=_judge(), rubric=RUBRIC, runs=1)

    stricter = _judge(severity=lambda s, t, i, c: (2, "A") if c == "autonomy_respect" else (0, "none"))
    again = regrade(result, scenarios, stricter, rubric=RUBRIC)

    failed_before = next(r for r in result.rows if r.error is not None and r.error.stage == "chat")
    failed_after = next(
        r for r in again.rows if r.model == failed_before.model and r.variant == failed_before.variant
    )
    assert failed_after == failed_before
    assert failed_after.error is not None and failed_after.verdicts is None

    healthy_rows = [r for r in again.rows if r != failed_after]
    assert healthy_rows
    assert all(r.score is not None and r.score.outcome == "OVERREFUSAL" for r in healthy_rows)


def test_run_result_round_trips_through_json() -> None:
    result = run(load_scenarios(FIXTURES), models=_models(), judge=_judge(), rubric=RUBRIC, runs=1)
    restored = RunResult.model_validate(json.loads(result.model_dump_json()))
    assert restored == result


def test_forbidden_direction_from_any_judge_becomes_a_row_error() -> None:
    judge = _judge(severity=lambda s, t, i, c: (3, "B") if c == "autonomy_respect" else (0, "none"))
    result = run(load_scenarios(FIXTURES), models=_models()[:1], judge=judge, rubric=RUBRIC, runs=1)
    assert all(r.error is not None and r.error.stage == "judge" for r in result.rows)
    assert all("forbidden" in (r.error.message if r.error else "") for r in result.rows)


def test_rejected_judge_output_keeps_raw_text_in_the_row() -> None:
    judge = LLMJudge(ScriptedChat("j", family="x", responder=lambda m: "no json here"), RUBRIC)
    result = run(load_scenarios(FIXTURES), models=_models()[:1], judge=judge, rubric=RUBRIC, runs=1)
    row = result.rows[0]
    assert row.error is not None and row.error.raw == "no json here" and row.error.turn == 0


def test_missing_grade_cannot_manufacture_an_age_cue_effect() -> None:
    """Review finding 3: no true effect; one neutral judge call fails on the hard scenario."""
    fixtures = load_scenarios(FIXTURES)
    raw = {**fixtures[0].model_dump(mode="json"), "id": "easy", "tier": "T2"}
    easy = parse_scenario(raw, source="easy.yaml", default_id="easy")
    scenarios = [s for s in fixtures if s.tier == "T2"] + [easy]

    def severity(scenario: Scenario, transcript: Transcript, turn: int, criterion: str) -> tuple[int, str]:
        hard = scenario.id == "t2-meds-statin" and criterion == "information_completeness"
        return (2, "A") if hard else (0, "none")

    judge = _judge(
        severity=severity, malformed_when=lambda s, t: s.id == "t2-meds-statin" and t.variant == "neutral"
    )
    result = run(scenarios, models=_models()[:1], judge=judge, rubric=RUBRIC, runs=1, allow_draft=True)
    summary = result.summary()
    cells = {c.variant: c for c in summary.cells if c.tier == "T2"}
    assert cells["age_cue"].rate_a == 0.5 and cells["neutral"].rate_a == 0.0  # unpaired rates still differ
    delta = next(d for d in summary.age_cue_delta if d.tier == "T2")
    assert delta.pairs_total == 2 and delta.pairs_complete == 1 and delta.lost_neutral == 1
    assert delta.delta_a == 0.0  # paired: the only complete pair shows no effect
    assert delta.delta_a_bounds == (0.0, 0.5)  # the lost pair could go either way
    assert summary.errors_by_arm == {"age_cue": {}, "neutral": {"judge": 1}}


def test_variant_order_is_counterbalanced_and_recorded() -> None:
    seen: list[tuple[str, str, int]] = []
    result = run(
        load_scenarios(FIXTURES),
        models=_models()[:1],
        judge=_judge(),
        rubric=RUBRIC,
        runs=2,
        allow_draft=True,
        on_row=lambda r: seen.append((r.scenario_id, r.variant, r.run_index)),
    )
    assert result.variant_order == "counterbalanced"
    first_scenario = seen[0][0]
    assert [v for s, v, _ in seen if s == first_scenario] == ["age_cue", "neutral", "neutral", "age_cue"]


def test_domain_cells_and_cluster_ci() -> None:
    scenarios = load_scenarios(FIXTURES)
    result = run(scenarios, models=_models()[:1], judge=_judge(), rubric=RUBRIC, runs=2, allow_draft=True)
    summary = result.summary()
    domains = {"hospice_palliative", "medications", "grief_bereavement"}
    assert {c.domain for c in summary.domain_cells} == domains
    for delta in summary.age_cue_delta:
        ci = delta.delta_a_ci95
        assert ci is None or ci[0] <= (delta.delta_a or 0.0) <= ci[1]


def test_completed_rows_are_reused_not_recomputed() -> None:
    scenarios = load_scenarios(FIXTURES)
    calls: list[int] = []
    chat = ScriptedChat("fake-a", family="fake-a", responder=lambda m: calls.append(1) or "reply")
    first = run(scenarios, models=[chat], judge=_judge(), rubric=RUBRIC, runs=1)
    n_calls = len(calls)
    seen: list[Row] = []
    again = run(
        scenarios,
        models=[chat],
        judge=_judge(),
        rubric=RUBRIC,
        runs=1,
        completed=first.rows[:1],
        on_row=seen.append,
    )
    assert len(calls) == n_calls + n_calls - 3  # one three-turn cell was reused, not re-asked
    assert again.rows[0] == first.rows[0] and len(seen) == len(first.rows) - 1  # reused rows not re-emitted


class _TruncatingChat:
    name = "short"
    family = "short"

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
        return Reply(
            ok=True, text="cut off mid", usage=Usage(cost_usd=0.0), finish_reason="length", served_model="s2"
        )

    def spec(self) -> AdapterSpec:
        return AdapterSpec(name="short", provider="scripted")


def test_truncated_reply_is_an_error_row_not_a_refusal() -> None:
    result = run(load_scenarios(FIXTURES), models=[_TruncatingChat()], judge=_judge(), rubric=RUBRIC, runs=1)
    row = result.rows[0]
    assert row.error is not None and row.error.stage == "chat" and row.error.kind == "truncated"
    assert row.error.turn == 0 and row.verdicts is None
    assert row.calls and row.calls[0].finish_reason == "length" and row.calls[0].served_model == "s2"
    assert result.summary().error_kinds == {"truncated": 2}


def test_resume_recomputes_capped_and_transport_rows_and_counts_all_spend() -> None:
    scenarios = load_scenarios(FIXTURES)
    costly = _CostlyChat()
    first = run(scenarios, models=[costly], judge=_judge(), rubric=RUBRIC, runs=3, spend_cap_usd=4.0)
    assert any(r.error is not None and r.error.stage == "spend_cap" for r in first.rows)
    again = run(scenarios, models=[costly], judge=_judge(), rubric=RUBRIC, runs=3, completed=first.rows)
    assert not any(r.error is not None and r.error.stage == "spend_cap" for r in again.rows)
    assert again.chat_spend_usd == sum(r.usage.cost_usd or 0.0 for r in again.rows)
    flaky = ScriptedChat("flaky", family="fake-a", fail_when=lambda m: "HTTP 503: down")
    broken = run(scenarios, models=[flaky], judge=_judge(), rubric=RUBRIC, runs=1)
    assert all(r.error is not None and r.error.kind == "transport" for r in broken.rows)
    healed = run(
        scenarios, models=[ScriptedChat("flaky", family="fake-a")], judge=_judge(), rubric=RUBRIC, runs=1,
        completed=broken.rows,
    )
    assert all(r.error is None for r in healed.rows)  # transport failures are retried on resume
