"""run() and regrade(): the deep pipeline module (ADR-004).

One call: promoted scenarios × variants × models × runs, each cell transcribed turn by turn,
judged, scored, and returned as a frozen Row. Failed chat calls, malformed judge output, and
spend-cap hits become rows; the family rule and empty runs are refused before the first paid
call. No clock, no files, no adapter construction in here.
"""

from __future__ import annotations

import random
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from kupuna_bench.chat import Chat, Message, Reply, Usage
from kupuna_bench.judge import Exchange, Judge, JudgeCallFailed, MalformedJudgeOutput, Transcript
from kupuna_bench.manifest import Manifest, ModelRef
from kupuna_bench.rubric import ForbiddenDirection, Rubric, TranscriptScore, Verdicts, score_transcript
from kupuna_bench.scenarios import VARIANTS, Scenario, Variant, dataset_sha256


class JudgeFamilyConflict(ValueError):
    """The judge shares a model family with a model under test."""


class NothingToRun(ValueError):
    """No models, or no runnable scenarios."""


class DatasetMismatch(ValueError):
    """regrade: a row's scenario is missing or its content changed."""


__all__ = ["ModelRef"]  # re-exported: ModelRef moved to kupuna_bench.manifest on 2026-09-09


class RowError(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["chat", "judge", "spend_cap"]
    turn: int | None = None
    message: str
    raw: str | None = None  # the judge output that was rejected, kept for audit (ADR-010)
    kind: str | None = None  # chat: transport, truncated, filtered, empty (ADR-013)


class CallMeta(BaseModel):
    """What the provider said about one model-under-test call (ADR-013)."""

    model_config = ConfigDict(frozen=True)

    turn: int
    finish_reason: str | None = None
    served_model: str | None = None
    provider: str | None = None
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    retried_for_length: bool = False


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
    calls: tuple[CallMeta, ...] = ()


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


class PairedDelta(BaseModel):
    """The age-cue contrast on matched units (scenario x model x run), ADR-011.

    `delta_*` is the mean over complete pairs of (age-cue failure - neutral failure); `*_bounds`
    lets every lost pair's missing arm be a pass or a fail; `*_ci95` is a scenario-cluster bootstrap.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    tier: str
    pairs_total: int = 0
    pairs_complete: int = 0
    lost_cue: int = 0
    lost_neutral: int = 0
    lost_both: int = 0
    delta_a: float | None = None
    delta_b: float | None = None
    delta_a_bounds: tuple[float, float] | None = None
    delta_b_bounds: tuple[float, float] | None = None
    delta_a_ci95: tuple[float, float] | None = None
    delta_b_ci95: tuple[float, float] | None = None


Delta = PairedDelta  # the pre-2026-09-09 name


class DomainCell(BaseModel):
    """Per (model, domain, variant) failure rates: the brief calls domain-level rates primary."""

    model_config = ConfigDict(frozen=True)

    model: str
    domain: str
    variant: str
    n: int
    graded: int
    rate_a: float | None
    rate_b: float | None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_signed(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}"


def _fmt_range(value: tuple[float, float] | None) -> str:
    return "n/a" if value is None else f"[{value[0]:+.2f}, {value[1]:+.2f}]"


class Summary(BaseModel):
    """Per (model, tier, variant) cells plus derived stats.

    `spread_by_tier` is the between-model spread of the Direction A rate on the age-cue
    variant, one number per tier (None where fewer than two models have a rate for that tier).
    """

    model_config = ConfigDict(frozen=True)

    total: int
    graded: int
    cells: tuple[Cell, ...]
    age_cue_delta: tuple[PairedDelta, ...]
    spread_by_tier: dict[str, float | None]
    errors: dict[str, int]
    domain_cells: tuple[DomainCell, ...] = ()
    errors_by_arm: dict[str, dict[str, int]] = {}
    error_kinds: dict[str, int] = {}

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
        lines.append(
            "| model | tier | pairs complete/total | lost cue/neutral/both | Δ A paired | Δ A bounds "
            "| Δ A 95% CI | Δ B paired | Δ B bounds | Δ B 95% CI |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for d in self.age_cue_delta:
            lines.append(
                f"| {d.model} | {d.tier} | {d.pairs_complete}/{d.pairs_total} | "
                f"{d.lost_cue}/{d.lost_neutral}/{d.lost_both} | {_fmt_signed(d.delta_a)} | "
                f"{_fmt_range(d.delta_a_bounds)} | {_fmt_range(d.delta_a_ci95)} | {_fmt_signed(d.delta_b)} | "
                f"{_fmt_range(d.delta_b_bounds)} | {_fmt_range(d.delta_b_ci95)} |"
            )
        if self.domain_cells:
            lines.append("")
            lines.append("| model | domain | variant | n | graded | A rate | B rate |")
            lines.append("|---|---|---|---|---|---|---|")
            for c in self.domain_cells:
                lines.append(
                    f"| {c.model} | {c.domain} | {c.variant} | {c.n} | {c.graded} | "
                    f"{_fmt(c.rate_a)} | {_fmt(c.rate_b)} |"
                )
        if self.errors:
            lines.append("")
            lines.append("errors: " + ", ".join(f"{k}={v}" for k, v in sorted(self.errors.items())))
            by_arm = "; ".join(
                f"{arm} " + (", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none")
                for arm, kinds in sorted(self.errors_by_arm.items())
            )
            lines.append(f"errors by arm: {by_arm}")
        if self.error_kinds:
            lines.append("error kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(self.error_kinds.items())))
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
    variant_order: str = "age_cue_first"  # runs before 2026-09-09; new runs are "counterbalanced"
    run_id: str | None = None
    manifest: Manifest | None = None
    source_run: str | None = None  # regrade: the run whose transcripts were re-judged
    fixture_scenarios: int = 0  # reviewed_by: fixture items in the run; any makes the record draft

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


def _call_meta(turn: int, reply: Reply) -> CallMeta:
    return CallMeta(
        turn=turn,
        finish_reason=reply.finish_reason,
        served_model=reply.served_model,
        provider=reply.provider,
        request_id=reply.request_id,
        input_tokens=reply.usage.input_tokens,
        output_tokens=reply.usage.output_tokens,
        cost_usd=reply.usage.cost_usd,
        retried_for_length=reply.retried_for_length,
    )


def _reply_problem(reply: Reply) -> tuple[str, str] | None:
    """(kind, message) when a reply cannot stand as the model's answer (ADR-013)."""
    if not reply.ok:
        return "transport", reply.error or "unknown error"
    if reply.finish_reason == "length":
        retried = " after one retry at double the limit" if reply.retried_for_length else ""
        return "truncated", f"reply cut off by the token limit{retried}"
    if reply.finish_reason == "filtered":
        return "filtered", "reply withheld by the provider's content filter"
    if not reply.text.strip():
        return "empty", "empty reply"
    return None


def _transcribe(
    model: Chat, scenario: Scenario, variant: Variant, system_prompt: str | None, budget: _Budget
) -> tuple[Transcript, Usage, RowError | None, tuple[CallMeta, ...]]:
    messages: list[Message] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    exchanges: list[Exchange] = []
    calls: list[CallMeta] = []
    usage = Usage(cost_usd=0.0)
    for index, user in enumerate(scenario.user_turns(variant)):
        messages.append({"role": "user", "content": user})
        reply = model.complete(messages)
        calls.append(_call_meta(index, reply))
        if reply.ok:
            usage = usage + reply.usage
            budget.add(reply.usage)
        problem = _reply_problem(reply)
        if problem is not None:
            kind, message = problem
            error = RowError(stage="chat", turn=index, message=message, kind=kind)
            return Transcript(variant=variant, exchanges=tuple(exchanges)), usage, error, tuple(calls)
        exchanges.append(Exchange(user=user, assistant=reply.text))
        messages.append({"role": "assistant", "content": reply.text})
    return Transcript(variant=variant, exchanges=tuple(exchanges)), usage, None, tuple(calls)


def _grade(
    judge: Judge, scenario: Scenario, transcript: Transcript, rubric: Rubric
) -> tuple[Verdicts | None, TranscriptScore | None, RowError | None]:
    try:
        verdicts = judge.grade(scenario, transcript)
    except MalformedJudgeOutput as exc:
        return None, None, RowError(
            stage="judge", turn=exc.turn, message=f"malformed: {exc.reason}", raw=exc.raw
        )
    except JudgeCallFailed as exc:
        return None, None, RowError(stage="judge", turn=exc.turn, message=f"call failed: {exc.reason}")
    try:
        rubric.check_directions(verdicts)
    except ForbiddenDirection as exc:
        return None, None, RowError(stage="judge", message=f"forbidden direction: {exc}")
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
    transcript, usage, error, calls = _transcribe(model, scenario, variant, system_prompt, budget)
    if error is not None:
        return Row(**base, transcript=transcript, usage=usage, error=error, calls=calls)
    verdicts, score, judge_error = _grade(judge, scenario, transcript, rubric)
    return Row(
        **base,
        transcript=transcript,
        usage=usage,
        verdicts=verdicts,
        score=score,
        error=judge_error,
        calls=calls,
    )


def _row_key(row: Row) -> tuple[str, str, str, int]:
    return (row.scenario_id, row.variant, row.model, row.run_index)


def _settled(row: Row) -> bool:
    """A journaled row worth keeping on resume: graded, judge-rejected, or a policy exclusion (ADR-013).

    Cells cut by the spend cap or lost to transport failures are recomputed instead."""
    if row.error is None or row.error.stage == "judge":
        return True
    return row.error.stage == "chat" and row.error.kind not in (None, "transport")


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
    manifest: Manifest | None = None,
    completed: Sequence[Row] = (),
) -> RunResult:
    """Transcribe, judge, and score every promoted scenario x variant x model x run cell.

    `spend_cap_usd` bounds model-under-test spend only. It is checked once between cells, not
    mid-cell, so a model's thread can overshoot the cap by up to one cell's worth of calls
    before the next check catches it. Judge spend is measured and reported separately
    (`RunResult.judge_spend_usd`) but is never capped. `completed` rows (from a journal) are
    reused verbatim for their cells and not re-emitted through `on_row`; `manifest` is recorded.
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
    done = {_row_key(row): row for row in completed if _settled(row)}
    for row in done.values():
        budget.add(row.usage)  # a resumed run's spend and cap cover the whole run, not the new cells only

    def work(model: Chat) -> list[Row]:
        produced: list[Row] = []
        for s_index, scenario in enumerate(selected):
            for run_index in range(runs):
                # Counterbalanced: the age-cue arm goes first on even (scenario, run) parities, second on odd.
                order = VARIANTS if (s_index + run_index) % 2 == 0 else tuple(reversed(VARIANTS))
                for variant in order:
                    reused = done.get((scenario.id, variant, model.name, run_index))
                    if reused is not None:
                        produced.append(reused)
                        continue
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
        variant_order="counterbalanced",
        run_id=manifest.run_id if manifest is not None else None,
        manifest=manifest,
        fixture_scenarios=sum(1 for s in selected if s.fixture),
    )


def regrade(
    result: RunResult,
    scenarios: Sequence[Scenario],
    judge: Judge,
    *,
    rubric: Rubric,
    source_run: str | None = None,
    manifest: Manifest | None = None,
) -> RunResult:
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
            "source_run": source_run,
            "manifest": manifest,
            "run_id": manifest.run_id if manifest is not None else None,
        }
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _fail_rate(row: Row, direction: str, pass_max: int) -> float | None:
    if row.score is None:
        return None
    severity = row.score.a_severity if direction == "A" else row.score.b_severity
    return 1.0 if severity > pass_max else 0.0


def _pair_bounds(cue: float | None, neutral: float | None) -> tuple[float, float]:
    """A pair's contribution when a missing arm could have been a pass or a fail."""
    cues = (cue,) if cue is not None else (0.0, 1.0)
    neutrals = (neutral,) if neutral is not None else (0.0, 1.0)
    values = [c - n for c in cues for n in neutrals]
    return min(values), max(values)


def _cluster_ci(pairs: Sequence[tuple[str, float]], *, seed: int, reps: int) -> tuple[float, float] | None:
    """Scenario-cluster bootstrap of the mean paired difference: resampling keeps every pair intact."""
    by_scenario: dict[str, list[float]] = {}
    for scenario_id, value in pairs:
        by_scenario.setdefault(scenario_id, []).append(value)
    clusters = list(by_scenario.values())
    if len(clusters) < 2 or reps < 1:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(reps):
        sample = [value for _ in clusters for value in rng.choice(clusters)]
        means.append(sum(sample) / len(sample))
    means.sort()
    return means[int(0.025 * len(means))], means[min(len(means) - 1, int(0.975 * len(means)))]


def _range_mean(pairs: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    if not pairs:
        return None
    return sum(lo for lo, _ in pairs) / len(pairs), sum(hi for _, hi in pairs) / len(pairs)


def paired_deltas(
    rows: Sequence[Row], *, pass_max_severity: int, seed: int = 0, reps: int = 1000
) -> tuple[PairedDelta, ...]:
    """The age-cue contrast per (model, tier) on matched (scenario, run) units; see PairedDelta."""
    units: dict[tuple[str, str, str, int], dict[str, Row]] = {}
    for row in rows:
        units.setdefault((row.model, row.tier, row.scenario_id, row.run_index), {})[row.variant] = row
    out: list[PairedDelta] = []
    for model, tier in sorted({(m, t) for m, t, _, _ in units}):
        total = complete = lost_cue = lost_neutral = lost_both = 0
        diffs: dict[str, list[tuple[str, float]]] = {"A": [], "B": []}
        bounds: dict[str, list[tuple[float, float]]] = {"A": [], "B": []}
        for (m, t, scenario_id, _), arms in sorted(units.items()):
            if (m, t) != (model, tier):
                continue
            total += 1
            cue, neutral = arms.get("age_cue"), arms.get("neutral")
            has_cue = cue is not None and cue.score is not None
            has_neutral = neutral is not None and neutral.score is not None
            if has_cue and has_neutral:
                complete += 1
            elif has_cue:
                lost_neutral += 1
            elif has_neutral:
                lost_cue += 1
            else:
                lost_both += 1
            for direction in ("A", "B"):
                c = _fail_rate(cue, direction, pass_max_severity) if cue is not None else None
                n = _fail_rate(neutral, direction, pass_max_severity) if neutral is not None else None
                bounds[direction].append(_pair_bounds(c, n))
                if c is not None and n is not None:
                    diffs[direction].append((scenario_id, c - n))
        out.append(
            PairedDelta(
                model=model,
                tier=tier,
                pairs_total=total,
                pairs_complete=complete,
                lost_cue=lost_cue,
                lost_neutral=lost_neutral,
                lost_both=lost_both,
                delta_a=_mean([value for _, value in diffs["A"]]),
                delta_b=_mean([value for _, value in diffs["B"]]),
                delta_a_bounds=_range_mean(bounds["A"]),
                delta_b_bounds=_range_mean(bounds["B"]),
                delta_a_ci95=_cluster_ci(diffs["A"], seed=seed, reps=reps),
                delta_b_ci95=_cluster_ci(diffs["B"], seed=seed, reps=reps),
            )
        )
    return tuple(out)


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
    by_domain: dict[tuple[str, str, str], list[Row]] = {}
    for row in rows:
        by_domain.setdefault((row.model, row.domain, row.variant), []).append(row)
    domain_cells: list[DomainCell] = []
    for (model, domain, variant), members in sorted(by_domain.items()):
        graded = [r for r in members if r.score is not None]
        domain_cells.append(
            DomainCell(
                model=model,
                domain=domain,
                variant=variant,
                n=len(members),
                graded=len(graded),
                rate_a=_mean([_fail_rate(r, "A", pass_max_severity) or 0.0 for r in graded]),
                rate_b=_mean([_fail_rate(r, "B", pass_max_severity) or 0.0 for r in graded]),
            )
        )
    deltas = paired_deltas(rows, pass_max_severity=pass_max_severity)
    # Between-model spread of the Direction A rate on the age-cue variant, one number per tier.
    spread: dict[str, float | None] = {}
    for tier in sorted({c.tier for c in cells}):
        rates = [
            c.rate_a for c in cells if c.tier == tier and c.variant == "age_cue" and c.rate_a is not None
        ]
        spread[tier] = (max(rates) - min(rates)) if len(rates) >= 2 else None
    errors = Counter(row.error.stage for row in rows if row.error is not None)
    error_kinds = Counter(row.error.kind for row in rows if row.error is not None and row.error.kind)
    errors_by_arm = {
        variant: dict(Counter(r.error.stage for r in rows if r.variant == variant and r.error is not None))
        for variant in VARIANTS
    }
    return Summary(
        total=len(rows),
        graded=sum(1 for r in rows if r.score is not None),
        cells=tuple(cells),
        age_cue_delta=deltas,
        spread_by_tier=spread,
        errors=dict(errors),
        domain_cells=tuple(domain_cells),
        errors_by_arm=errors_by_arm,
        error_kinds=dict(error_kinds),
    )
