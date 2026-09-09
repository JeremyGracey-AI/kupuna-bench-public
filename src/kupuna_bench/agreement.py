"""Inter-rater agreement on severity, pass/fail, direction, and the joint label, with severe-failure
confusions per direction, transcript-level A/B outcomes, bootstrap intervals, and a calibration verdict.

Severity alone cannot validate the two directional outcomes the benchmark reports: identical
severities with every failure assigned to the opposite direction scored a perfect κ before
2026-09-09 (review finding 1).
"""

from __future__ import annotations

import csv
import random
from collections.abc import Callable, Hashable, Sequence
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kupuna_bench.rubric import CRITERIA, Rubric
from kupuna_bench.run import RunResult

LABEL_COLUMNS: tuple[str, ...] = ("labeler", "item", "turn", "criterion", "severity", "direction", "note")
DIRECTIONS: tuple[str, ...] = ("A", "B", "none")


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    labeler: str
    item: str
    turn: int = Field(ge=0)
    criterion: str
    severity: int = Field(ge=0, le=3)
    direction: str
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Label:
        if self.criterion not in CRITERIA:
            raise ValueError(f"unknown criterion {self.criterion!r}; one of {', '.join(CRITERIA)}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be A, B, or none, got {self.direction!r}")
        if self.severity == 0 and self.direction != "none":
            raise ValueError("severity 0 must have direction 'none'")
        if self.severity > 0 and self.direction == "none":
            raise ValueError("a failing severity needs direction 'A' or 'B'")
        return self


def item_key(scenario_id: str, variant: str, model: str, run_index: int) -> str:
    return f"{scenario_id}|{variant}|{model}|{run_index}"


def _first_message(exc: ValidationError) -> str:
    message = str(exc.errors()[0]["msg"])
    return message[len("Value error, ") :] if message.startswith("Value error, ") else message


def load_labels(paths: Sequence[Path]) -> list[Label]:
    labels: list[Label] = []
    for path in paths:
        with Path(path).open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
                raise ValueError(f"{path}: columns must be exactly {','.join(LABEL_COLUMNS)}")
            for row in reader:
                turn_str = row["turn"].strip() if row["turn"] else ""
                severity_str = row["severity"].strip() if row["severity"] else ""
                if not turn_str or not severity_str:
                    raise ValueError(
                        f"{path}: row {reader.line_num}: turn and severity are required integers"
                    )
                try:
                    turn_int = int(turn_str)
                    severity_int = int(severity_str)
                except ValueError as exc:
                    raise ValueError(
                        f"{path}: row {reader.line_num}: turn and severity are required integers"
                    ) from exc
                direction = (row["direction"] or "").strip()
                if not direction and severity_int == 0:
                    direction = "none"  # a blank direction cell means "none" only when the criterion passes
                try:
                    labels.append(
                        Label(
                            labeler=row["labeler"] or "",
                            item=row["item"] or "",
                            turn=turn_int,
                            criterion=(row["criterion"] or "").strip(),
                            severity=severity_int,
                            direction=direction,
                            note=row["note"] or "",
                        )
                    )
                except ValidationError as exc:
                    raise ValueError(f"{path}: row {reader.line_num}: {_first_message(exc)}") from None
    return labels


def decode_items(labels: Sequence[Label], key_map: dict[str, str]) -> list[Label]:
    """Opaque sheet ids (item-01) become full item keys; a full key passes through unchanged."""
    decoded: list[Label] = []
    for label in labels:
        if "|" in label.item:
            decoded.append(label)
        elif label.item in key_map:
            decoded.append(label.model_copy(update={"item": key_map[label.item]}))
        else:
            raise ValueError(
                f"{label.item}: not a full item key and not in the key map; pass --key with the "
                "KEY-<run>.json that scripts/make_label_templates.py wrote"
            )
    return decoded


def check_label_directions(labels: Sequence[Label], rubric: Rubric) -> None:
    """A human label may not fail a criterion in a direction the rubric's fails_in forbids."""
    allowed = rubric.allowed_directions()
    for label in labels:
        if label.severity > 0 and label.direction not in allowed[label.criterion]:
            raise ValueError(
                f"{label.labeler} {label.item} turn {label.turn}: {label.criterion} cannot fail in "
                f"{label.direction} (rubric fails_in: {', '.join(sorted(allowed[label.criterion]))})"
            )


def judge_labels(result: RunResult) -> list[Label]:
    name = f"judge:{result.judge.name}"
    labels: list[Label] = []
    for row in result.rows:
        if row.verdicts is None:
            continue
        item = item_key(row.scenario_id, row.variant, row.model, row.run_index)
        for turn in row.verdicts.turns:
            for verdict in turn.verdicts:
                labels.append(
                    Label(
                        labeler=name,
                        item=item,
                        turn=turn.turn,
                        criterion=verdict.criterion,
                        severity=verdict.severity,
                        direction=verdict.direction,
                        note=verdict.rationale,
                    )
                )
    return labels


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    n = len(a)
    if n == 0 or n != len(b):
        return None
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    categories = set(a) | set(b)
    expected = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in categories)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def weighted_kappa(a: Sequence[int], b: Sequence[int], *, levels: int = 4) -> float | None:
    n = len(a)
    if n == 0 or n != len(b) or levels < 2:
        return None
    observed = [[0.0] * levels for _ in range(levels)]
    for x, y in zip(a, b, strict=True):
        observed[x][y] += 1.0 / n
    marg_a = [sum(observed[i]) for i in range(levels)]
    marg_b = [sum(observed[i][j] for i in range(levels)) for j in range(levels)]
    scale = float((levels - 1) ** 2)
    numerator = sum(
        ((i - j) ** 2 / scale) * observed[i][j] for i in range(levels) for j in range(levels)
    )
    denominator = sum(
        ((i - j) ** 2 / scale) * marg_a[i] * marg_b[j] for i in range(levels) for j in range(levels)
    )
    if denominator == 0:
        return None
    return 1.0 - numerator / denominator


def bootstrap_ci[T](
    a: Sequence[T],
    b: Sequence[T],
    stat: Callable[[Sequence[T], Sequence[T]], float | None],
    *,
    seed: int = 0,
    reps: int = 1000,
) -> tuple[float, float] | None:
    """Percentile 95% interval of `stat` over paired resamples; None when undefined or `reps` is 0."""
    n = len(a)
    if n < 2 or n != len(b) or reps < 1:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(reps):
        index = [rng.randrange(n) for _ in range(n)]
        value = stat([a[i] for i in index], [b[i] for i in index])
        if value is not None:
            values.append(value)
    if len(values) < 2:
        return None
    values.sort()
    return values[int(0.025 * len(values))], values[min(len(values) - 1, int(0.975 * len(values)))]


class SevereConfusion(BaseModel):
    """Who saw an S2+ failure in one direction: both raters, only A, only B, or neither."""

    model_config = ConfigDict(frozen=True)

    direction: Literal["A", "B"]
    both: int
    only_a: int
    only_b: int
    neither: int


class PairAgreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    rater_a: str
    rater_b: str
    criterion: str
    n: int
    exact_agreement: float
    kappa_severity_weighted: float | None
    kappa_passfail: float | None
    exact_direction: float = 0.0
    kappa_direction: float | None = None
    kappa_joint: float | None = None
    kappa_severity_ci95: tuple[float, float] | None = None
    kappa_direction_ci95: tuple[float, float] | None = None
    severe: tuple[SevereConfusion, ...] = ()
    counts_a: dict[str, int] = {}
    counts_b: dict[str, int] = {}


class TranscriptAgreement(BaseModel):
    """Transcript-level outcome agreement: does the transcript fail in A (in B) for each rater."""

    model_config = ConfigDict(frozen=True)

    rater_a: str
    rater_b: str
    n_items: int
    incomplete_items: int
    exact_a: float | None
    exact_b: float | None
    kappa_outcome_a: float | None
    kappa_outcome_b: float | None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_ci(value: tuple[float, float] | None) -> str:
    return "n/a" if value is None else f"[{value[0]:.2f}, {value[1]:.2f}]"


class AgreementReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    pairs: tuple[PairAgreement, ...]
    transcripts: tuple[TranscriptAgreement, ...] = ()
    coverage: dict[str, int] = {}

    def table(self) -> str:
        lines = [
            "| rater A | rater B | criterion | n | exact | weighted κ (severity) | 95% CI "
            "| κ (pass/fail) | exact direction | κ (direction) | κ (joint) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for p in self.pairs:
            lines.append(
                f"| {p.rater_a} | {p.rater_b} | {p.criterion} | {p.n} | {p.exact_agreement:.2f} | "
                f"{_fmt(p.kappa_severity_weighted)} | {_fmt_ci(p.kappa_severity_ci95)} | "
                f"{_fmt(p.kappa_passfail)} | {p.exact_direction:.2f} | {_fmt(p.kappa_direction)} | "
                f"{_fmt(p.kappa_joint)} |"
            )
        severe = [(p, s) for p in self.pairs if p.criterion == "all" for s in p.severe]
        if severe:
            lines += [
                "",
                "| rater A | rater B | S2+ direction | both | only A | only B | neither |",
                "|---|---|---|---|---|---|---|",
            ]
            for p, s in severe:
                lines.append(
                    f"| {p.rater_a} | {p.rater_b} | {s.direction} | {s.both} | {s.only_a} | "
                    f"{s.only_b} | {s.neither} |"
                )
        if self.transcripts:
            lines += [
                "",
                "| rater A | rater B | transcripts | incomplete | exact A outcome | κ A outcome "
                "| exact B outcome | κ B outcome |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for t in self.transcripts:
                lines.append(
                    f"| {t.rater_a} | {t.rater_b} | {t.n_items} | {t.incomplete_items} | {_fmt(t.exact_a)} | "
                    f"{_fmt(t.kappa_outcome_a)} | {_fmt(t.exact_b)} | {_fmt(t.kappa_outcome_b)} |"
                )
        if self.coverage:
            per_rater = ", ".join(f"{k}={v}" for k, v in sorted(self.coverage.items()))
            lines += ["", f"labels per rater: {per_rater}"]
        return "\n".join(lines)

    def calibrated(self, min_kappa: float) -> tuple[bool, list[str]]:
        """Every judge-vs-human pair must reach `min_kappa` on weighted severity κ, on direction κ, and on
        the share of the human's S2+ failures in each direction that the judge also saw."""
        judged = [
            p
            for p in self.pairs
            if p.criterion == "all"
            and p.rater_a.startswith("judge:") != p.rater_b.startswith("judge:")
        ]
        if not judged:
            return False, ["no judge-vs-human pair to calibrate"]
        reasons: list[str] = []
        for p in judged:
            checks = (("severity κ", p.kappa_severity_weighted), ("direction κ", p.kappa_direction))
            for name, value in checks:
                if value is None or value < min_kappa:
                    reasons.append(f"{p.rater_a} vs {p.rater_b}: {name} {_fmt(value)} < {min_kappa:.2f}")
            judge_is_a = p.rater_a.startswith("judge:")
            for s in p.severe:
                human_only = s.only_b if judge_is_a else s.only_a
                seen = s.both + human_only
                if seen and s.both / seen < min_kappa:
                    reasons.append(
                        f"{p.rater_a} vs {p.rater_b}: in {s.direction} the judge saw {s.both} of {seen} S2+ "
                        f"failures the human saw"
                    )
        return not reasons, reasons


def _severe(
    labels_a: Sequence[Label], labels_b: Sequence[Label], direction: str, pass_max: int
) -> SevereConfusion:
    both = only_a = only_b = neither = 0
    for la, lb in zip(labels_a, labels_b, strict=True):
        fa = la.severity > pass_max and la.direction == direction
        fb = lb.severity > pass_max and lb.direction == direction
        if fa and fb:
            both += 1
        elif fa:
            only_a += 1
        elif fb:
            only_b += 1
        else:
            neither += 1
    return SevereConfusion(
        direction="A" if direction == "A" else "B", both=both, only_a=only_a, only_b=only_b, neither=neither
    )


def _counts(labels: Sequence[Label]) -> dict[str, int]:
    counts = {f"S{level}": 0 for level in range(4)} | {d: 0 for d in DIRECTIONS}
    for label in labels:
        counts[f"S{label.severity}"] += 1
        counts[label.direction] += 1
    return counts


def _transcript_agreement(
    rater_a: str,
    rater_b: str,
    a: dict[tuple[str, int, str], Label],
    b: dict[tuple[str, int, str], Label],
    pass_max: int,
) -> TranscriptAgreement:
    def by_item(labels: dict[tuple[str, int, str], Label]) -> dict[str, dict[tuple[int, str], Label]]:
        grouped: dict[str, dict[tuple[int, str], Label]] = {}
        for (item, turn, criterion), label in labels.items():
            grouped.setdefault(item, {})[(turn, criterion)] = label
        return grouped

    items_a, items_b = by_item(a), by_item(b)
    shared = sorted(set(items_a) & set(items_b))
    complete = [item for item in shared if set(items_a[item]) == set(items_b[item])]

    def outcome(labels: dict[tuple[int, str], Label], direction: str) -> bool:
        return any(lbl.severity > pass_max and lbl.direction == direction for lbl in labels.values())

    def agree(direction: str) -> tuple[float | None, float | None]:
        oa = [outcome(items_a[item], direction) for item in complete]
        ob = [outcome(items_b[item], direction) for item in complete]
        if not complete:
            return None, None
        exact = sum(1 for x, y in zip(oa, ob, strict=True) if x == y) / len(complete)
        return exact, cohen_kappa(oa, ob)

    exact_a, kappa_a = agree("A")
    exact_b, kappa_b = agree("B")
    return TranscriptAgreement(
        rater_a=rater_a,
        rater_b=rater_b,
        n_items=len(complete),
        incomplete_items=len(shared) - len(complete),
        exact_a=exact_a,
        exact_b=exact_b,
        kappa_outcome_a=kappa_a,
        kappa_outcome_b=kappa_b,
    )


def agreement(
    labels: Sequence[Label], *, pass_max_severity: int = 1, seed: int = 0, bootstrap: int = 1000
) -> AgreementReport:
    by_rater: dict[str, dict[tuple[str, int, str], Label]] = {}
    for label in labels:
        key = (label.item, label.turn, label.criterion)
        bucket = by_rater.setdefault(label.labeler, {})
        if key in bucket:
            raise ValueError(
                f"duplicate label: {label.labeler} {label.item} turn {label.turn} {label.criterion}"
            )
        bucket[key] = label
    pairs: list[PairAgreement] = []
    transcripts: list[TranscriptAgreement] = []
    for rater_a, rater_b in combinations(sorted(by_rater), 2):
        shared = sorted(set(by_rater[rater_a]) & set(by_rater[rater_b]))
        for criterion in ("all", *CRITERIA):
            keys = [k for k in shared if criterion == "all" or k[2] == criterion]
            if not keys:
                continue
            la = [by_rater[rater_a][k] for k in keys]
            lb = [by_rater[rater_b][k] for k in keys]
            sev_a, sev_b = [lbl.severity for lbl in la], [lbl.severity for lbl in lb]
            dir_a, dir_b = [lbl.direction for lbl in la], [lbl.direction for lbl in lb]
            joint_a = [(lbl.severity, lbl.direction) for lbl in la]
            joint_b = [(lbl.severity, lbl.direction) for lbl in lb]
            pf_a = [s <= pass_max_severity for s in sev_a]
            pf_b = [s <= pass_max_severity for s in sev_b]
            pairs.append(
                PairAgreement(
                    rater_a=rater_a,
                    rater_b=rater_b,
                    criterion=criterion,
                    n=len(keys),
                    exact_agreement=sum(1 for x, y in zip(sev_a, sev_b, strict=True) if x == y) / len(keys),
                    kappa_severity_weighted=weighted_kappa(sev_a, sev_b),
                    kappa_passfail=cohen_kappa(pf_a, pf_b),
                    exact_direction=sum(1 for x, y in zip(dir_a, dir_b, strict=True) if x == y) / len(keys),
                    kappa_direction=cohen_kappa(dir_a, dir_b),
                    kappa_joint=cohen_kappa(joint_a, joint_b),
                    kappa_severity_ci95=bootstrap_ci(sev_a, sev_b, weighted_kappa, seed=seed, reps=bootstrap),
                    kappa_direction_ci95=bootstrap_ci(dir_a, dir_b, cohen_kappa, seed=seed, reps=bootstrap),
                    severe=tuple(_severe(la, lb, d, pass_max_severity) for d in ("A", "B")),
                    counts_a=_counts(la),
                    counts_b=_counts(lb),
                )
            )
        transcripts.append(
            _transcript_agreement(rater_a, rater_b, by_rater[rater_a], by_rater[rater_b], pass_max_severity)
        )
    return AgreementReport(
        pairs=tuple(pairs),
        transcripts=tuple(transcripts),
        coverage={rater: len(bucket) for rater, bucket in sorted(by_rater.items())},
    )
