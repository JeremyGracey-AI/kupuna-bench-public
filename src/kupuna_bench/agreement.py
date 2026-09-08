"""Inter-rater agreement for ordinal severity (quadratic-weighted κ) and pass/fail (plain κ)."""

from __future__ import annotations

import csv
from collections.abc import Hashable, Sequence
from itertools import combinations
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from kupuna_bench.rubric import CRITERIA
from kupuna_bench.run import RunResult

LABEL_COLUMNS: tuple[str, ...] = ("labeler", "item", "turn", "criterion", "severity", "direction", "note")


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    labeler: str
    item: str
    turn: int = Field(ge=0)
    criterion: str
    severity: int = Field(ge=0, le=3)
    direction: str
    note: str = ""


def item_key(scenario_id: str, variant: str, model: str, run_index: int) -> str:
    return f"{scenario_id}|{variant}|{model}|{run_index}"


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
                labels.append(
                    Label(
                        labeler=row["labeler"] or "",
                        item=row["item"] or "",
                        turn=turn_int,
                        criterion=row["criterion"] or "",
                        severity=severity_int,
                        direction=row["direction"] or "",
                        note=row["note"] or "",
                    )
                )
    return labels


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


class PairAgreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    rater_a: str
    rater_b: str
    criterion: str
    n: int
    exact_agreement: float
    kappa_severity_weighted: float | None
    kappa_passfail: float | None


class AgreementReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    pairs: tuple[PairAgreement, ...]

    def table(self) -> str:
        fmt = _fmt
        lines = [
            "| rater A | rater B | criterion | n | exact | weighted κ (severity) | κ (pass/fail) |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in self.pairs:
            lines.append(
                f"| {p.rater_a} | {p.rater_b} | {p.criterion} | {p.n} | {p.exact_agreement:.2f} | "
                f"{fmt(p.kappa_severity_weighted)} | {fmt(p.kappa_passfail)} |"
            )
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def agreement(labels: Sequence[Label], *, pass_max_severity: int = 1) -> AgreementReport:
    by_rater: dict[str, dict[tuple[str, int, str], Label]] = {}
    for label in labels:
        by_rater.setdefault(label.labeler, {})[(label.item, label.turn, label.criterion)] = label
    pairs: list[PairAgreement] = []
    for rater_a, rater_b in combinations(sorted(by_rater), 2):
        shared = sorted(set(by_rater[rater_a]) & set(by_rater[rater_b]))
        for criterion in ("all", *CRITERIA):
            keys = [k for k in shared if criterion == "all" or k[2] == criterion]
            if not keys:
                continue
            sev_a = [by_rater[rater_a][k].severity for k in keys]
            sev_b = [by_rater[rater_b][k].severity for k in keys]
            pf_a = [s <= pass_max_severity for s in sev_a]
            pf_b = [s <= pass_max_severity for s in sev_b]
            pairs.append(
                PairAgreement(
                    rater_a=rater_a,
                    rater_b=rater_b,
                    criterion=criterion,
                    n=len(keys),
                    exact_agreement=sum(1 for x, y in zip(sev_a, sev_b, strict=True) if x == y)
                    / len(keys),
                    kappa_severity_weighted=weighted_kappa(sev_a, sev_b),
                    kappa_passfail=cohen_kappa(pf_a, pf_b),
                )
            )
    return AgreementReport(pairs=tuple(pairs))
