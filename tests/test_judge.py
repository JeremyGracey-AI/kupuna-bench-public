import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from kupuna_bench.chat import Message, Reply, ScriptedChat, Usage
from kupuna_bench.judge import (
    Exchange,
    Judge,
    JudgeCallFailed,
    LLMJudge,
    MalformedJudgeOutput,
    ScriptedJudge,
    Transcript,
    build_turn_messages,
    parse_turn_verdict,
    parse_verdicts,
    verdicts_all_pass,
)
from kupuna_bench.rubric import CRITERIA, TurnVerdict, Verdicts, load_rubric
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"


def _transcript(n: int = 2) -> Transcript:
    return Transcript(
        variant="age_cue", exchanges=tuple(Exchange(user=f"u{i}", assistant=f"a{i}") for i in range(n))
    )


def test_transcript_turns() -> None:
    assert _transcript(3).turns == 3
    assert Transcript(variant="neutral", exchanges=()).turns == 0


def test_parse_verdicts_extracts_json_from_prose() -> None:
    payload = verdicts_all_pass(2).model_dump()
    text = "Here is my grading:\n" + json.dumps(payload) + "\nDone."
    assert parse_verdicts(text, n_turns=2) == verdicts_all_pass(2)


def test_parse_verdicts_rejects_wrong_turn_count() -> None:
    with pytest.raises(MalformedJudgeOutput, match="expected 3 turns, got 2"):
        parse_verdicts(verdicts_all_pass(2).model_dump_json(), n_turns=3)


def test_parse_verdicts_rejects_invalid_json_and_schema() -> None:
    with pytest.raises(MalformedJudgeOutput, match="no JSON object"):
        parse_verdicts("I refuse to grade.", n_turns=1)
    bad = {"turns": [{"turn": 0, "verdicts": [{"criterion": "x", "severity": 9, "direction": "A"}]}]}
    with pytest.raises(MalformedJudgeOutput):
        parse_verdicts(json.dumps(bad), n_turns=1)


def test_parse_verdicts_tolerates_braces_inside_strings() -> None:
    verdicts = verdicts_all_pass(1)
    turn = verdicts.turns[0]
    quoted = turn.verdicts[0].model_copy(update={"rationale": "looks like {this} and x} too"})
    updated_turn = turn.model_copy(update={"verdicts": (quoted, *turn.verdicts[1:])})
    updated = Verdicts(turns=(updated_turn,))
    text = "prose " + updated.model_dump_json() + " trailing }"
    assert parse_verdicts(text, n_turns=1) == updated


def test_parse_verdicts_rejects_truncated_json() -> None:
    text = verdicts_all_pass(1).model_dump_json()[:40]
    with pytest.raises(MalformedJudgeOutput, match="invalid JSON"):
        parse_verdicts(text, n_turns=1)


def test_scripted_judge_all_pass_and_malformed() -> None:
    scenario = load_scenarios(FIXTURES)[0]
    judge = ScriptedJudge(malformed_for=frozenset({"t3-grief-hopelessness"}))
    assert isinstance(judge, Judge)
    verdicts = judge.grade(scenario, _transcript(3))
    assert len(verdicts.turns) == 3 and all(v.severity == 0 for t in verdicts.turns for v in t.verdicts)
    grief = next(s for s in load_scenarios(FIXTURES) if s.id == "t3-grief-hopelessness")
    with pytest.raises(MalformedJudgeOutput):
        judge.grade(grief, _transcript(3))


def test_scripted_judge_severity_hook() -> None:
    scenario = load_scenarios(FIXTURES)[0]

    def severity(scn: object, transcript: Transcript, turn: int, criterion: str) -> tuple[int, str]:
        return (2, "A") if criterion == "autonomy_respect" and turn == 1 else (0, "none")

    verdicts = ScriptedJudge(severity=severity).grade(scenario, _transcript(2))
    flagged = [v for t in verdicts.turns for v in t.verdicts if v.severity]
    assert len(flagged) == 1 and flagged[0].criterion == "autonomy_respect" and verdicts.turns[1].turn == 1


def test_turn_messages_carry_only_the_prefix_and_no_condition_metadata() -> None:
    rubric = load_rubric()
    statin = next(s for s in load_scenarios(FIXTURES) if s.id == "t2-meds-statin")
    first = json.loads(build_turn_messages(statin, _transcript(3), rubric, turn=0)[1]["content"])
    assert [c["turn"] for c in first["conversation"]] == [0] and first["grade_turn"] == 0
    text = json.dumps(first)
    for leaked in ("u1", "a2", "variant", "persona", "situation", "risk_cues", "age_cue", "84"):
        assert leaked not in text, leaked
    last = json.loads(build_turn_messages(statin, _transcript(3), rubric, turn=2)[1]["content"])
    assert [c["turn"] for c in last["conversation"]] == [0, 1, 2]
    assert last["answer_key"]["expected"].startswith("A concrete list")  # the per-turn key for turn 2
    assert last["scenario"]["tier"] == "T2" and "id" in last["scenario"]
    with pytest.raises(ValueError, match="turn 3"):
        build_turn_messages(statin, _transcript(3), rubric, turn=3)


def _turn_responder(seen: list[dict[str, object]]) -> Callable[[list[Message]], str]:
    def responder(messages: list[Message]) -> str:
        payload = json.loads(messages[-1]["content"])
        seen.append(payload)
        turn = int(payload["grade_turn"])
        return TurnVerdict(turn=turn, verdicts=verdicts_all_pass(1).turns[0].verdicts).model_dump_json()

    return responder


def test_llm_judge_makes_one_prefix_call_per_turn() -> None:
    rubric = load_rubric()
    scenario = load_scenarios(FIXTURES)[0]
    seen: list[dict[str, object]] = []
    judge = LLMJudge(ScriptedChat("m", family="mistralai", responder=_turn_responder(seen)), rubric)
    verdicts = judge.grade(scenario, _transcript(3))
    assert len(verdicts.turns) == 3
    assert [len(p["conversation"]) for p in seen] == [1, 2, 3]


def test_parse_turn_verdict_rejects_wrong_turn_and_keeps_raw() -> None:
    text = TurnVerdict(turn=1, verdicts=verdicts_all_pass(1).turns[0].verdicts).model_dump_json()
    with pytest.raises(MalformedJudgeOutput, match="expected turn 0, got 1") as excinfo:
        parse_turn_verdict(text, turn=0)
    assert excinfo.value.raw == text and excinfo.value.turn == 0
    with pytest.raises(MalformedJudgeOutput, match="no JSON object") as excinfo:
        parse_turn_verdict("nothing here", turn=0)
    assert excinfo.value.raw == "nothing here"


def test_llm_judge_parses_chat_output_and_tracks_usage() -> None:
    rubric = load_rubric()
    scenario = load_scenarios(FIXTURES)[0]
    seen: list[dict[str, object]] = []
    chat = ScriptedChat("mistral-large", family="mistralai", responder=_turn_responder(seen))
    judge = LLMJudge(chat, rubric)
    assert judge.family == "mistralai" and judge.name == "llm:mistral-large"
    verdicts = judge.grade(scenario, _transcript(2))
    assert len(verdicts.turns) == 2 and len(seen) == 2
    assert judge.usage.cost_usd == 0.0 and judge.usage.input_tokens > 0


def test_llm_judge_raises_call_failed_and_malformed() -> None:
    rubric = load_rubric()
    scenario = load_scenarios(FIXTURES)[0]
    dead = LLMJudge(ScriptedChat("j", family="x", fail_when=lambda m: "HTTP 503: down"), rubric)
    with pytest.raises(JudgeCallFailed, match="HTTP 503"):
        dead.grade(scenario, _transcript(1))
    chatty = LLMJudge(ScriptedChat("j", family="x", responder=lambda m: "no json here"), rubric)
    with pytest.raises(MalformedJudgeOutput):
        chatty.grade(scenario, _transcript(1))
    assert set(CRITERIA) == {
        "information_completeness",
        "autonomy_respect",
        "risk_flagging",
        "non_condescending_tone",
        "appropriate_referral",
    }


def test_parse_verdicts_with_rubric_rejects_forbidden_direction() -> None:
    verdicts = verdicts_all_pass(1)
    turn = verdicts.turns[0]
    flipped = tuple(
        v.model_copy(update={"severity": 3, "direction": "B"}) if v.criterion == "autonomy_respect" else v
        for v in turn.verdicts
    )
    text = Verdicts(turns=(turn.model_copy(update={"verdicts": flipped}),)).model_dump_json()
    parse_verdicts(text, n_turns=1)  # the schema alone accepts it (the review's reproduction)
    with pytest.raises(MalformedJudgeOutput, match="cannot fail in B"):
        parse_verdicts(text, n_turns=1, rubric=load_rubric())


def test_llm_judge_treats_truncated_json_as_malformed() -> None:
    class Cut:
        name = "cut"
        family = "cut"

        def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
            return Reply(ok=True, text='{"turn": 0, "verd', usage=Usage(cost_usd=0.0), finish_reason="length")

    with pytest.raises(MalformedJudgeOutput, match="truncated") as excinfo:
        LLMJudge(Cut(), load_rubric()).grade(load_scenarios(FIXTURES)[0], _transcript(1))  # type: ignore[arg-type]
    assert excinfo.value.raw == '{"turn": 0, "verd'
