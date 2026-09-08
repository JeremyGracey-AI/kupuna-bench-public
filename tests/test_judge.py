import json
from pathlib import Path

import pytest

from kupuna_bench.chat import Message, ScriptedChat
from kupuna_bench.judge import (
    Exchange,
    Judge,
    JudgeCallFailed,
    LLMJudge,
    MalformedJudgeOutput,
    ScriptedJudge,
    Transcript,
    build_judge_messages,
    parse_verdicts,
    verdicts_all_pass,
)
from kupuna_bench.rubric import CRITERIA, Verdicts, load_rubric
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


def test_build_judge_messages_carries_rubric_and_keys() -> None:
    rubric = load_rubric()
    statin = next(s for s in load_scenarios(FIXTURES) if s.id == "t2-meds-statin")
    messages = build_judge_messages(statin, _transcript(3), rubric)
    assert messages[0]["role"] == "system" and "appropriate_referral" in messages[0]["content"]
    user = messages[1]["content"]
    assert "A concrete list of questions" in user  # the per-turn key for turn 2
    assert '"turn": 2' in user and "a2" in user and "u0" in user


def test_llm_judge_parses_chat_output_and_tracks_usage() -> None:
    rubric = load_rubric()
    scenario = load_scenarios(FIXTURES)[0]
    seen: list[list[Message]] = []

    def responder(messages: list[Message]) -> str:
        seen.append(list(messages))
        return verdicts_all_pass(2).model_dump_json()

    judge = LLMJudge(ScriptedChat("mistral-large", family="mistralai", responder=responder), rubric)
    assert judge.family == "mistralai" and judge.name == "llm:mistral-large"
    verdicts = judge.grade(scenario, _transcript(2))
    assert len(verdicts.turns) == 2 and seen and seen[0][0]["role"] == "system"
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
