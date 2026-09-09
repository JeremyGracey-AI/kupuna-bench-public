"""Scenario schema, loader, and PI-facing validation.

The YAML a clinician writes is the most important interface in this repo. Four required
fields (domain, tier, turns, answer_key); a turn is a quoted string (identical in both
variants), a mapping with `user` (identical, and able to carry its own `key`), or a mapping
with age_cue and neutral; status: promoted requires reviewed_by.
Errors are reported for every file at once, each with the fix in the message.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

Domain = Literal[
    "end_of_life_planning",
    "hospice_palliative",
    "medications",
    "driving_cessation",
    "grief_bereavement",
    "loneliness_companionship",
]
Tier = Literal["T1", "T2", "T3"]
Status = Literal["draft", "reviewed", "promoted"]
Variant = Literal["age_cue", "neutral"]

VARIANTS: tuple[Variant, ...] = ("age_cue", "neutral")
TIERS: tuple[Tier, ...] = ("T1", "T2", "T3")
FIXTURE_REVIEWER = "fixture"  # reserved: test-only provenance; such items are never reported


class AnswerKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: str
    warranted_warnings: tuple[str, ...] = ()
    unwarranted_warnings: tuple[str, ...] = ()
    referral: str = "only when risk cues warrant it, never instead of the answer"


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    age_cue: str
    neutral: str
    key: AnswerKey | None = None


class Persona(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    age: int | None = None
    living_situation: str | None = None
    cognitive_cues: str | None = None
    proxy: str | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    domain: Domain
    tier: Tier
    turns: tuple[Turn, ...]
    answer_key: AnswerKey
    title: str = ""
    situation: str = ""
    risk_cues: tuple[str, ...] = ()
    persona: Persona | None = None
    status: Status = "draft"
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> Scenario:
        if not self.turns:
            raise ValueError("turns: needs at least one turn")
        if all(turn.age_cue == turn.neutral for turn in self.turns):
            raise ValueError("turns: no turn differs between age_cue and neutral; at least one must")
        if self.status != "draft" and not self.reviewed_by:
            raise ValueError(
                f"status: {self.status} needs reviewed_by. Add reviewed_by: <your name>, "
                "or set status: draft."
            )
        return self

    @property
    def fixture(self) -> bool:
        """Test data by construction (`reviewed_by: fixture`); a run containing one is never reportable."""
        return self.reviewed_by == FIXTURE_REVIEWER

    def user_turns(self, variant: Variant) -> list[str]:
        return [getattr(turn, variant) for turn in self.turns]

    def key_for(self, turn_index: int) -> AnswerKey:
        key = self.turns[turn_index].key
        return key if key is not None else self.answer_key

    def content_sha256(self) -> str:
        data = self.model_dump(mode="json", exclude={"status", "reviewed_by"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


class ScenarioError(ValueError):
    """Every problem found, one PI-facing message per problem."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("\n".join(messages))
        self.messages = messages


def _normalize_turns(raw_turns: Any, source: str) -> tuple[list[dict[str, Any]], list[str]]:
    turns: list[dict[str, Any]] = []
    messages: list[str] = []
    if not isinstance(raw_turns, list):
        return turns, [f"{source} turns: must be a list of turns"]
    for index, item in enumerate(cast(list[Any], raw_turns)):
        if isinstance(item, str):
            turns.append({"age_cue": item, "neutral": item})
        elif isinstance(item, dict):
            mapping = dict(cast(dict[str, Any], item))
            has_age, has_neutral = "age_cue" in mapping, "neutral" in mapping
            if "user" in mapping:
                if has_age or has_neutral:
                    messages.append(
                        f"{source} turns[{index}]: use either user or age_cue and neutral, not both "
                        "(user means the same text in both variants)."
                    )
                else:
                    text = mapping.pop("user")
                    mapping["age_cue"] = mapping["neutral"] = text
            elif has_age != has_neutral:
                present, missing = ("age_cue", "neutral") if has_age else ("neutral", "age_cue")
                messages.append(
                    f"{source} turns[{index}]: has {present} but no {missing}. A turn that differs needs "
                    "both texts; an identical turn is just a quoted string."
                )
            turns.append(mapping)
        else:
            messages.append(
                f"{source} turns[{index}]: must be a quoted string or a mapping with age_cue and neutral"
            )
    return turns, messages


def _translate(error: dict[str, Any], raw: dict[str, Any], source: str) -> str:
    loc = ".".join(str(part) for part in error["loc"])
    if loc == "tier":
        return (
            f"{source} tier: must be T1, T2 or T3 (got {raw.get('tier')!r}). "
            "T1 low, T2 moderate, T3 high; see docs/rubric.md."
        ).replace("'", "")
    message = str(error["msg"])
    if message.startswith("Value error, "):
        message = message[len("Value error, ") :]
    if loc:
        if message.startswith(loc.split(".")[0] + ":"):
            return f"{source} {message}"
        return f"{source} {loc}: {message}"
    return f"{source} {message}"


def parse_scenario(raw: dict[str, Any], *, source: str, default_id: str) -> Scenario:
    data = dict(raw)
    data.setdefault("id", default_id)
    turns, messages = _normalize_turns(data.get("turns"), source)
    data["turns"] = turns
    if messages:
        raise ScenarioError(messages)
    try:
        return Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioError(
            [_translate(cast(dict[str, Any], error), data, source) for error in exc.errors()]
        ) from None


def key_warnings(scenario: Scenario) -> list[str]:
    """PI-facing: a shared key over several turns expects later disclosures too early (review finding 2)."""
    missing = [index for index, turn in enumerate(scenario.turns) if turn.key is None]
    if len(scenario.turns) < 2 or not missing:
        return []
    advice = (
        "a fact disclosed in a later turn cannot be expected earlier. Give each turn its own key "
        "(turns[i].key) that names only what the person has said by that turn."
    )
    if len(missing) == len(scenario.turns):
        return [f"{scenario.id}: {len(scenario.turns)} turns share one answer key; {advice}"]
    names = ", ".join(f"turns[{index}]" for index in missing)
    partial = f"{names} fall back to the scenario answer key while other turns have keys"
    return [f"{scenario.id}: {partial}; {advice}"]


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load every *.yaml under `directory` (recursively), reporting every error at once."""
    directory = Path(directory)
    scenarios: list[Scenario] = []
    messages: list[str] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.rglob("*.yaml")):
        source = path.relative_to(directory).as_posix()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = f"line {mark.line + 1}" if mark is not None else "line ?"
            messages.append(f"{source} {line}: not valid YAML, check indentation")
            continue
        if not isinstance(raw, dict):
            messages.append(f"{source}: must be a mapping of fields, not a list or a bare value")
            continue
        try:
            scenario = parse_scenario(cast(dict[str, Any], raw), source=source, default_id=path.stem)
        except ScenarioError as exc:
            messages.extend(exc.messages)
            continue
        if scenario.id in seen:
            messages.append(f"{source}: duplicate scenario id '{scenario.id}' (also in {seen[scenario.id]})")
            continue
        seen[scenario.id] = source
        scenarios.append(scenario)
    if messages:
        raise ScenarioError(messages)
    return sorted(scenarios, key=lambda s: s.id)


def dataset_sha256(scenarios: Sequence[Scenario]) -> str:
    entries = sorted((s.id, s.content_sha256()) for s in scenarios)
    joined = "\n".join(f"{scenario_id}:{content_hash}" for scenario_id, content_hash in entries)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
