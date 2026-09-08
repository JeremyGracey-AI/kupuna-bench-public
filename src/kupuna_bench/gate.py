"""Minimum-bar gate. Keyless CI proves plumbing only: every cell present, every row graded."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from kupuna_bench.run import RunResult, expected_cells


class Gate(BaseModel):
    model_config = ConfigDict(frozen=True)

    well_formed: float = 0.0
    coverage: float = 0.0


PLUMBING_GATE = Gate(well_formed=1.0, coverage=1.0)


def gate_metrics(result: RunResult, *, n_scenarios: int) -> dict[str, float]:
    summary = result.summary()
    expected = expected_cells(n_scenarios, len(result.models), result.runs)
    return {
        "well_formed": summary.well_formed(),
        "coverage": (summary.total / expected) if expected else 0.0,
    }


def check_gate(metrics: dict[str, float], gate: Gate) -> tuple[bool, list[str]]:
    gate_dict = cast(dict[str, float], gate.model_dump())
    failures = [
        f"{name}: {metrics.get(name, 0.0):.3f} < required {required:.3f}"
        for name, required in gate_dict.items()
        if metrics.get(name, 0.0) < required
    ]
    return not failures, failures


def load_gate_from_meta(meta: dict[str, Any]) -> Gate:
    """Build the gate from golden `_meta.thresholds`. No hardcoded fallback on purpose."""
    thresholds = meta.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("golden _meta.thresholds is missing; the golden must carry its own bar")
    spec: dict[str, Any] = dict(cast(dict[str, Any], thresholds))
    unknown = [name for name in spec if name not in Gate.model_fields]
    if unknown:
        raise ValueError(f"golden _meta.thresholds names unknown metric(s): {unknown}")
    return Gate(**{name: float(value) for name, value in spec.items()})
