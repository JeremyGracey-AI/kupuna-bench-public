"""The Judge seam: grades a transcript into per-turn verdicts on the rubric criteria.

Two adapters: LLMJudge (a Chat plus the rubric, JSON output parsed strictly) and
ScriptedJudge (deterministic, for tests and keyless CI). Malformed model output is rejected
at this seam with MalformedJudgeOutput rather than silently repaired (Provenance's door).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from kupuna_bench.chat import Chat, Message, Usage
from kupuna_bench.rubric import CRITERIA, CriterionVerdict, Rubric, TurnVerdict, Verdicts
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
    def __init__(self, reason: str) -> None:
        super().__init__(f"judge output rejected: {reason}")
        self.reason = reason


class JudgeCallFailed(JudgeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"judge call failed: {reason}")
        self.reason = reason


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


def parse_verdicts(text: str, *, n_turns: int) -> Verdicts:
    payload = first_json_object(text)
    try:
        verdicts = Verdicts.model_validate(payload)
    except ValidationError as exc:
        raise MalformedJudgeOutput(f"schema: {exc.errors()[0]['msg']}") from None
    if len(verdicts.turns) != n_turns:
        raise MalformedJudgeOutput(f"expected {n_turns} turns, got {len(verdicts.turns)}")
    return verdicts


def build_judge_messages(scenario: Scenario, transcript: Transcript, rubric: Rubric) -> list[Message]:
    turns_payload: list[dict[str, Any]] = []
    for index, exchange in enumerate(transcript.exchanges):
        key = scenario.key_for(index)
        turns_payload.append(
            {
                "turn": index,
                "user": exchange.user,
                "assistant": exchange.assistant,
                "answer_key": key.model_dump(mode="json"),
            }
        )
    user_payload = {
        "scenario": {
            "id": scenario.id,
            "domain": scenario.domain,
            "tier": scenario.tier,
            "tier_definition": rubric.item_tiers.get(scenario.tier, ""),
            "situation": scenario.situation,
            "risk_cues": list(scenario.risk_cues),
            "variant": transcript.variant,
            "persona": scenario.persona.model_dump(mode="json") if scenario.persona else None,
        },
        "turns": turns_payload,
    }
    return [
        {"role": "system", "content": rubric.judge_instructions()},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=1)},
    ]


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
    ) -> None:
        self.name = name
        self.family = family
        self._severity = severity
        self._malformed_for = malformed_for
        self.usage = Usage(cost_usd=0.0)

    def grade(self, scenario: Scenario, transcript: Transcript) -> Verdicts:
        if scenario.id in self._malformed_for:
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
        self._chat = chat
        self._rubric = rubric
        self.name = f"llm:{chat.name}"
        self.family = chat.family
        self.usage = Usage(cost_usd=0.0)
        self._lock = threading.Lock()

    def grade(self, scenario: Scenario, transcript: Transcript) -> Verdicts:
        messages: Sequence[Message] = build_judge_messages(scenario, transcript, self._rubric)
        reply = self._chat.complete(messages, json_mode=True)
        with self._lock:
            self.usage = self.usage + reply.usage
        if not reply.ok:
            raise JudgeCallFailed(reply.error or "unknown error")
        return parse_verdicts(reply.text, n_turns=transcript.turns)
