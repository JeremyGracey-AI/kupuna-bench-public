"""The Judge seam: grades a transcript into per-turn verdicts on the rubric criteria.

Two adapters: LLMJudge (a Chat plus the rubric; one call per reply, each seeing only the
conversation up to that reply and that turn's answer key, ADR-010) and ScriptedJudge
(deterministic, for tests and keyless CI). Malformed model output is rejected at this seam with
MalformedJudgeOutput, which keeps the raw text, rather than silently repaired (Provenance's door).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from kupuna_bench.chat import Chat, Message, Usage
from kupuna_bench.rubric import (
    CRITERIA,
    CriterionVerdict,
    ForbiddenDirection,
    Rubric,
    TurnVerdict,
    Verdicts,
)
from kupuna_bench.scenarios import Scenario, Variant


class Exchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    user: str
    assistant: str


class Transcript(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant: Variant
    exchanges: tuple[Exchange, ...]

    @property
    def turns(self) -> int:
        return len(self.exchanges)


class JudgeError(RuntimeError):
    """Base class: the judge could not produce verdicts for this transcript."""


class MalformedJudgeOutput(JudgeError):
    """`raw` is the rejected text and `turn` the reply being graded, both kept for the row's audit trail."""

    def __init__(self, reason: str, *, raw: str | None = None, turn: int | None = None) -> None:
        super().__init__(f"judge output rejected: {reason}")
        self.reason = reason
        self.raw = raw
        self.turn = turn


class JudgeCallFailed(JudgeError):
    def __init__(self, reason: str, *, turn: int | None = None) -> None:
        super().__init__(f"judge call failed: {reason}")
        self.reason = reason
        self.turn = turn


@runtime_checkable
class Judge(Protocol):
    name: str
    family: str
    usage: Usage

    def grade(self, scenario: Scenario, transcript: Transcript) -> Verdicts: ...


def verdicts_all_pass(n_turns: int) -> Verdicts:
    return Verdicts(
        turns=tuple(
            TurnVerdict(
                turn=i,
                verdicts=tuple(CriterionVerdict(criterion=c, severity=0, direction="none") for c in CRITERIA),
            )
            for i in range(n_turns)
        )
    )


def first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise MalformedJudgeOutput("no JSON object in output")
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise MalformedJudgeOutput(f"invalid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise MalformedJudgeOutput("top-level JSON is not an object")
    return cast(dict[str, Any], parsed)


def parse_verdicts(text: str, *, n_turns: int, rubric: Rubric | None = None) -> Verdicts:
    payload = first_json_object(text)
    try:
        verdicts = Verdicts.model_validate(payload)
    except ValidationError as exc:
        raise MalformedJudgeOutput(f"schema: {exc.errors()[0]['msg']}") from None
    if len(verdicts.turns) != n_turns:
        raise MalformedJudgeOutput(f"expected {n_turns} turns, got {len(verdicts.turns)}")
    if rubric is not None:
        try:
            rubric.check_directions(verdicts)
        except ForbiddenDirection as exc:
            raise MalformedJudgeOutput(str(exc)) from None
    return verdicts


def build_turn_messages(
    scenario: Scenario, transcript: Transcript, rubric: Rubric, *, turn: int
) -> list[Message]:
    """The judge sees the conversation up to and including the reply it grades, that turn's key, and
    the item's domain and tier. Not the variant, persona, situation, risk cues, or any later turn
    (ADR-010): a fact the person has not yet disclosed cannot be expected, and the experimental
    condition cannot steer the grade."""
    if not 0 <= turn < transcript.turns:
        raise ValueError(f"turn {turn} is not in the transcript (0..{transcript.turns - 1})")
    conversation = [
        {"turn": index, "user": exchange.user, "assistant": exchange.assistant}
        for index, exchange in enumerate(transcript.exchanges[: turn + 1])
    ]
    user_payload: dict[str, Any] = {
        "scenario": {
            "id": scenario.id,
            "domain": scenario.domain,
            "tier": scenario.tier,
            "tier_definition": rubric.item_tiers.get(scenario.tier, ""),
        },
        "conversation": conversation,
        "grade_turn": turn,
        "answer_key": scenario.key_for(turn).model_dump(mode="json"),
    }
    return [
        {"role": "system", "content": rubric.judge_instructions()},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=1)},
    ]


def parse_turn_verdict(text: str, *, turn: int, rubric: Rubric | None = None) -> TurnVerdict:
    """One reply's verdicts. The request fixes the graded turn, so an omitted `turn` is filled from
    it; a stated turn that contradicts the request is rejected. Every rejection keeps the raw text
    and the turn."""
    try:
        verdict = TurnVerdict.model_validate({"turn": turn, **first_json_object(text)})
    except MalformedJudgeOutput as exc:
        raise MalformedJudgeOutput(exc.reason, raw=text, turn=turn) from None
    except ValidationError as exc:
        raise MalformedJudgeOutput(f"schema: {exc.errors()[0]['msg']}", raw=text, turn=turn) from None
    if verdict.turn != turn:
        raise MalformedJudgeOutput(f"expected turn {turn}, got {verdict.turn}", raw=text, turn=turn)
    if rubric is not None:
        try:
            rubric.check_turn_directions(verdict)
        except ForbiddenDirection as exc:
            raise MalformedJudgeOutput(str(exc), raw=text, turn=turn) from None
    return verdict


SeverityHook = Callable[[Scenario, Transcript, int, str], tuple[int, str]]


class ScriptedJudge:
    """Deterministic judge. Default: every criterion passes. `severity` overrides per (turn, criterion)."""

    def __init__(
        self,
        name: str = "scripted-judge",
        family: str = "scripted-judge",
        *,
        severity: SeverityHook | None = None,
        malformed_for: frozenset[str] = frozenset(),
        malformed_when: Callable[[Scenario, Transcript], bool] | None = None,
    ) -> None:
        self.name = name
        self.family = family
        self._severity = severity
        self._malformed_for = malformed_for
        self._malformed_when = malformed_when
        self.usage = Usage(cost_usd=0.0)

    def grade(self, scenario: Scenario, transcript: Transcript) -> Verdicts:
        if scenario.id in self._malformed_for:
            raise MalformedJudgeOutput("scripted malformed output")
        if self._malformed_when is not None and self._malformed_when(scenario, transcript):
            raise MalformedJudgeOutput("scripted malformed output")
        if self._severity is None:
            return verdicts_all_pass(transcript.turns)
        turns: list[TurnVerdict] = []
        for index in range(transcript.turns):
            verdicts: list[CriterionVerdict] = []
            for criterion in CRITERIA:
                level, direction = self._severity(scenario, transcript, index, criterion)
                verdicts.append(
                    CriterionVerdict(criterion=criterion, severity=level, direction=cast(Any, direction))
                )
            turns.append(TurnVerdict(turn=index, verdicts=tuple(verdicts)))
        return Verdicts(turns=tuple(turns))


class LLMJudge:
    """A Chat plus the rubric. `usage` accumulates judge spend across calls (thread-safe)."""

    def __init__(self, chat: Chat, rubric: Rubric) -> None:
        self.chat = chat
        self._chat = chat
        self._rubric = rubric
        self.name = f"llm:{chat.name}"
        self.family = chat.family
        self.usage = Usage(cost_usd=0.0)
        self._lock = threading.Lock()

    def grade(self, scenario: Scenario, transcript: Transcript) -> Verdicts:
        """One call per reply with the conversation prefix only; any failed turn fails the transcript."""
        turns: list[TurnVerdict] = []
        for turn in range(transcript.turns):
            messages: Sequence[Message] = build_turn_messages(scenario, transcript, self._rubric, turn=turn)
            reply = self._chat.complete(messages, json_mode=True)
            with self._lock:
                self.usage = self.usage + reply.usage
            if not reply.ok:
                raise JudgeCallFailed(reply.error or "unknown error", turn=turn)
            if reply.finish_reason == "length":
                raise MalformedJudgeOutput("truncated judge output", raw=reply.text, turn=turn)
            turns.append(parse_turn_verdict(reply.text, turn=turn, rubric=self._rubric))
        return Verdicts(turns=tuple(turns))
