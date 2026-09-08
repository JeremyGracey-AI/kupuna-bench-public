"""run() and regrade(): the deep pipeline module (ADR-004).

One call: promoted scenarios × variants × models × runs, each cell transcribed turn by turn,
judged, scored, and returned as a frozen Row. Failed chat calls, malformed judge output, and
spend-cap hits become rows; the family rule and empty runs are refused before the first paid
call. No clock, no files, no adapter construction in here.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from kupuna_bench.chat import Chat, Message, Usage
from kupuna_bench.judge import Exchange, Judge, JudgeCallFailed, MalformedJudgeOutput, Transcript
from kupuna_bench.rubric import Rubric, TranscriptScore, Verdicts, score_transcript
from kupuna_bench.scenarios import VARIANTS, Scenario, Variant, dataset_sha256


class JudgeFamilyConflict(ValueError):
    """The judge shares a model family with a model under test."""


class NothingToRun(ValueError):
    """No models, or no runnable scenarios."""


class DatasetMismatch(ValueError):
    """regrade: a row's scenario is missing or its content changed."""


class ModelRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    family: str


class RowError(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["chat", "judge", "spend_cap"]
    turn: int | None = None
    message: str


class Row(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_sha256: str
    variant: Variant
    tier: str
    domain: str
    status: str
    model: str
    family: str
    run_index: int
    transcript: Transcript
    verdicts: Verdicts | None = None
    score: TranscriptScore | None = None
    error: RowError | None = None
    usage: Usage = Usage()


class Cell(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    tier: str
    variant: str
    n: int
    graded: int
    rate_a: float | None
    rate_b: float | None
    mean_a: float | None
    mean_b: float | None


class Delta(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    tier: str
    delta_a: float | None
    delta_b: float | None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


class Summary(BaseModel):
    """Per (model, tier, variant) cells plus derived stats.

    `spread_by_tier` is the between-model spread of the Direction A rate on the age-cue
    variant, one number per tier (None where fewer than two models have a rate for that tier).
    """

    model_config = ConfigDict(frozen=True)

    total: int
    graded: int
    cells: tuple[Cell, ...]
    age_cue_delta: tuple[Delta, ...]
    spread_by_tier: dict[str, float | None]
    errors: dict[str, int]

    def well_formed(self) -> float:
        return self.graded / self.total if self.total else 0.0

    def table(self) -> str:
        lines = [
            "| model | tier | variant | n | graded | A rate | B rate | mean A | mean B |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for c in self.cells:
            lines.append(
                f"| {c.model} | {c.tier} | {c.variant} | {c.n} | {c.graded} | "
                f"{_fmt(c.rate_a)} | {_fmt(c.rate_b)} | {_fmt(c.mean_a)} | {_fmt(c.mean_b)} |"
            )
        lines.append("")
        lines.append("| model | tier | age-cue delta A | age-cue delta B |")
        lines.append("|---|---|---|---|")
        for d in self.age_cue_delta:
            da = "n/a" if d.delta_a is None else f"{d.delta_a:+.2f}"
            db = "n/a" if d.delta_b is None else f"{d.delta_b:+.2f}"
            lines.append(f"| {d.model} | {d.tier} | {da} | {db} |")
        if self.errors:
            lines.append("")
            lines.append("errors: " + ", ".join(f"{k}={v}" for k, v in sorted(self.errors.items())))
        return "\n".join(lines)


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_sha256: str
    rubric_version: str
    pass_max_severity: int
    models: tuple[ModelRef, ...]
    judge: ModelRef
    runs: int
    allow_draft: bool
    skipped_draft: int
    rows: tuple[Row, ...]
    chat_spend_usd: float
    judge_spend_usd: float | None
    spend_usd: float | None
    unknown_cost_calls: int

    def summary(self) -> Summary:
        return summarize(self.rows, pass_max_severity=self.pass_max_severity)


def expected_cells(n_scenarios: int, n_models: int, runs: int) -> int:
    return n_scenarios * len(VARIANTS) * n_models * runs


class _Budget:
    def __init__(self, cap: float | None) -> None:
        self.cap = cap
        self.spent = 0.0
        self.unknown = 0
        self._lock = threading.Lock()

    def add(self, usage: Usage) -> None:
        with self._lock:
            if usage.cost_usd is None:
                self.unknown += 1
            else:
                self.spent += usage.cost_usd

    def exhausted(self) -> bool:
        with self._lock:
            return self.cap is not None and self.spent >= self.cap


def _transcribe(
    model: Chat, scenario: Scenario, variant: Variant, system_prompt: str | None, budget: _Budget
) -> tuple[Transcript, Usage, RowError | None]:
    messages: list[Message] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    exchanges: list[Exchange] = []
    usage = Usage(cost_usd=0.0)
    for index, user in enumerate(scenario.user_turns(variant)):
        messages.append({"role": "user", "content": user})
        reply = model.complete(messages)
        if not reply.ok:
            return (
                Transcript(variant=variant, exchanges=tuple(exchanges)),
                usage,
                RowError(stage="chat", turn=index, message=reply.error or "unknown error"),
            )
        usage = usage + reply.usage
        budget.add(reply.usage)
        exchanges.append(Exchange(user=user, assistant=reply.text))
        messages.append({"role": "assistant", "content": reply.text})
    return Transcript(variant=variant, exchanges=tuple(exchanges)), usage, None


def _grade(
    judge: Judge, scenario: Scenario, transcript: Transcript, rubric: Rubric
) -> tuple[Verdicts | None, TranscriptScore | None, RowError | None]:
    try:
        verdicts = judge.grade(scenario, transcript)
    except MalformedJudgeOutput as exc:
        return None, None, RowError(stage="judge", message=f"malformed: {exc.reason}")
    except JudgeCallFailed as exc:
        return None, None, RowError(stage="judge", message=f"call failed: {exc.reason}")
    return verdicts, score_transcript(verdicts, pass_max_severity=rubric.pass_max_severity), None


def _cell(
    scenario: Scenario,
    variant: Variant,
    model: Chat,
    run_index: int,
    judge: Judge,
    rubric: Rubric,
    budget: _Budget,
    system_prompt: str | None,
) -> Row:
    base: dict[str, Any] = {
        "scenario_id": scenario.id,
        "scenario_sha256": scenario.content_sha256(),
        "variant": variant,
        "tier": scenario.tier,
        "domain": scenario.domain,
        "status": scenario.status,
        "model": model.name,
        "family": model.family,
        "run_index": run_index,
    }
    if budget.exhausted():
        return Row(
            **base,
            transcript=Transcript(variant=variant, exchanges=()),
            usage=Usage(cost_usd=0.0),
            error=RowError(stage="spend_cap", message=f"spend cap {budget.cap} USD reached before this cell"),
        )
    transcript, usage, error = _transcribe(model, scenario, variant, system_prompt, budget)
    if error is not None:
        return Row(**base, transcript=transcript, usage=usage, error=error)
    verdicts, score, judge_error = _grade(judge, scenario, transcript, rubric)
    return Row(**base, transcript=transcript, usage=usage, verdicts=verdicts, score=score, error=judge_error)


def _row_key(row: Row) -> tuple[str, str, str, int]:
    return (row.scenario_id, row.variant, row.model, row.run_index)


def _check_families(models: Sequence[ModelRef], judge_name: str, judge_family: str) -> None:
    conflicts = [m.name for m in models if m.family == judge_family]
    if conflicts:
        raise JudgeFamilyConflict(
            f"judge {judge_name} is family {judge_family!r}, the same as models under test {conflicts}; "
            "pick a judge from a family that is not under test (ADR-003)"
        )


def run(
    scenarios: Sequence[Scenario],
    *,
    models: Sequence[Chat],
    judge: Judge,
    rubric: Rubric,
    runs: int = 3,
    allow_draft: bool = False,
    spend_cap_usd: float | None = None,
    system_prompt: str | None = None,
    on_row: Callable[[Row], None] | None = None,
) -> RunResult:
    """Transcribe, judge, and score every promoted scenario x variant x model x run cell.

    `spend_cap_usd` bounds model-under-test spend only. It is checked once between cells, not
    mid-cell, so a model's thread can overshoot the cap by up to one cell's worth of calls
    before the next check catches it. Judge spend is measured and reported separately
    (`RunResult.judge_spend_usd`) but is never capped.
    """
    models = list(models)
    if runs < 1:
        raise ValueError(f"runs must be >= 1, got {runs}")
    names = [m.name for m in models]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate model names: {names}")
    if not models:
        raise NothingToRun("no models under test")
    refs = tuple(ModelRef(name=m.name, family=m.family) for m in models)
    _check_families(refs, judge.name, judge.family)
    selected = [s for s in scenarios if allow_draft or s.status == "promoted"]
    skipped = len(scenarios) - len(selected)
    if not selected:
        raise NothingToRun(
            f"0 runnable scenarios ({skipped} excluded as unpromoted; "
            "pass allow_draft=True to include drafts)"
        )
    budget = _Budget(spend_cap_usd)
    emit_lock = threading.Lock()

    def work(model: Chat) -> list[Row]:
        produced: list[Row] = []
        for scenario in selected:
            for variant in VARIANTS:
                for run_index in range(runs):
                    row = _cell(scenario, variant, model, run_index, judge, rubric, budget, system_prompt)
                    produced.append(row)
                    if on_row is not None:
                        with emit_lock:
                            on_row(row)
        return produced

    judge_before = judge.usage
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        per_model = list(pool.map(work, models))
    judge_after = judge.usage
    rows = tuple(sorted(chain.from_iterable(per_model), key=_row_key))
    judge_spend_usd = (judge_after - judge_before).cost_usd
    spend_usd = budget.spent + judge_spend_usd if judge_spend_usd is not None else None
    return RunResult(
        dataset_sha256=dataset_sha256(selected),
        rubric_version=rubric.version,
        pass_max_severity=rubric.pass_max_severity,
        models=refs,
        judge=ModelRef(name=judge.name, family=judge.family),
        runs=runs,
        allow_draft=allow_draft,
        skipped_draft=skipped,
        rows=rows,
        chat_spend_usd=budget.spent,
        judge_spend_usd=judge_spend_usd,
        spend_usd=spend_usd,
        unknown_cost_calls=budget.unknown,
    )


def regrade(result: RunResult, scenarios: Sequence[Scenario], judge: Judge, *, rubric: Rubric) -> RunResult:
    """Re-judge every kept transcript with a different judge; chat-failed and capped rows stay verbatim."""
    _check_families(result.models, judge.name, judge.family)
    by_id = {s.id: s for s in scenarios}
    mismatched = sorted(
        {
            row.scenario_id
            for row in result.rows
            if row.scenario_id not in by_id or by_id[row.scenario_id].content_sha256() != row.scenario_sha256
        }
    )
    if mismatched:
        raise DatasetMismatch(f"scenario content changed or missing since the run: {mismatched}")
    judge_before = judge.usage
    rows: list[Row] = []
    for row in result.rows:
        if row.error is not None and row.error.stage in ("chat", "spend_cap"):
            rows.append(row)
            continue
        verdicts, score, error = _grade(judge, by_id[row.scenario_id], row.transcript, rubric)
        rows.append(row.model_copy(update={"verdicts": verdicts, "score": score, "error": error}))
    judge_after = judge.usage
    delta_cost = (judge_after - judge_before).cost_usd
    if result.judge_spend_usd is not None and delta_cost is not None:
        judge_spend_usd = result.judge_spend_usd + delta_cost
    else:
        judge_spend_usd = None
    spend_usd = result.chat_spend_usd + judge_spend_usd if judge_spend_usd is not None else None
    return result.model_copy(
        update={
            "judge": ModelRef(name=judge.name, family=judge.family),
            "rubric_version": rubric.version,
            "pass_max_severity": rubric.pass_max_severity,
            "rows": tuple(sorted(rows, key=_row_key)),
            "judge_spend_usd": judge_spend_usd,
            "spend_usd": spend_usd,
        }
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(rows: Sequence[Row], *, pass_max_severity: int) -> Summary:
    groups: dict[tuple[str, str, str], list[Row]] = {}
    for row in rows:
        groups.setdefault((row.model, row.tier, row.variant), []).append(row)
    cells: list[Cell] = []
    for (model, tier, variant), members in sorted(groups.items()):
        graded = [r for r in members if r.score is not None]
        a_fail = [1.0 if r.score and r.score.a_severity > pass_max_severity else 0.0 for r in graded]
        b_fail = [1.0 if r.score and r.score.b_severity > pass_max_severity else 0.0 for r in graded]
        cells.append(
            Cell(
                model=model,
                tier=tier,
                variant=variant,
                n=len(members),
                graded=len(graded),
                rate_a=_mean(a_fail),
                rate_b=_mean(b_fail),
                mean_a=_mean([float(r.score.a_severity) for r in graded if r.score]),
                mean_b=_mean([float(r.score.b_severity) for r in graded if r.score]),
            )
        )
    by_key = {(c.model, c.tier, c.variant): c for c in cells}
    deltas: list[Delta] = []
    for model, tier in sorted({(c.model, c.tier) for c in cells}):
        cue, neutral = by_key.get((model, tier, "age_cue")), by_key.get((model, tier, "neutral"))
        da = db = None
        if cue and neutral and cue.rate_a is not None and neutral.rate_a is not None:
            da = cue.rate_a - neutral.rate_a
        if cue and neutral and cue.rate_b is not None and neutral.rate_b is not None:
            db = cue.rate_b - neutral.rate_b
        deltas.append(Delta(model=model, tier=tier, delta_a=da, delta_b=db))
    # Between-model spread of the Direction A rate on the age-cue variant, one number per tier.
    spread: dict[str, float | None] = {}
    for tier in sorted({c.tier for c in cells}):
        rates = [
            c.rate_a for c in cells if c.tier == tier and c.variant == "age_cue" and c.rate_a is not None
        ]
        spread[tier] = (max(rates) - min(rates)) if len(rates) >= 2 else None
    errors = Counter(row.error.stage for row in rows if row.error is not None)
    return Summary(
        total=len(rows),
        graded=sum(1 for r in rows if r.score is not None),
        cells=tuple(cells),
        age_cue_delta=tuple(deltas),
        spread_by_tier=spread,
        errors=dict(errors),
    )
