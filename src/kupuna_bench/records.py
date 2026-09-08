"""Append-only run records: results/run-YYYY-MM-DD-N.md.

Lifted from harness-eval's records module. Exclusive-create only; N is monotonic within a day
and gaps are never refilled; a FAIL must name its shortfalls; a run against an unpromoted
golden carries `draft: true` in the record itself.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, cast

from kupuna_bench.run import RunResult

RECORD_VERSION = 1
_RUN_RE = re.compile(r"^run-(\d{4}-\d{2}-\d{2})-(\d+)\.md$")
_REQUIRED = (
    "system", "dataset_sha256", "rubric_version", "models", "judge", "runs",
    "gate", "verdict", "timestamp", "driver", "metrics",
)


def _validate(facts: dict[str, Any]) -> None:
    missing = [key for key in _REQUIRED if key not in facts]
    if missing:
        raise ValueError(f"record facts missing required keys: {missing}")
    if facts["verdict"] not in ("PASS", "FAIL"):
        raise ValueError(f"verdict must be 'PASS' or 'FAIL', got {facts['verdict']!r}")
    if facts["verdict"] == "FAIL" and not facts.get("shortfalls"):
        raise ValueError("a FAIL verdict must carry named shortfalls")


def facts_from_result(
    result: RunResult,
    *,
    gate_name: str,
    verdict: str,
    shortfalls: list[str],
    timestamp: str,
    driver: str,
    draft: bool,
) -> dict[str, Any]:
    summary = result.summary()
    metrics: dict[str, Any] = {
        "well_formed": summary.well_formed(),
        "total_rows": summary.total,
        "graded_rows": summary.graded,
        "spend_usd": result.spend_usd if result.spend_usd is not None else "unknown",
        "chat_spend_usd": result.chat_spend_usd,
        "judge_spend_usd": result.judge_spend_usd if result.judge_spend_usd is not None else "unknown",
        "unknown_cost_calls": result.unknown_cost_calls,
    }
    for cell in summary.cells:
        prefix = f"{cell.model}/{cell.tier}/{cell.variant}"
        metrics[f"{prefix}/rate_a"] = cell.rate_a if cell.rate_a is not None else "n/a"
        metrics[f"{prefix}/rate_b"] = cell.rate_b if cell.rate_b is not None else "n/a"
    return {
        "system": "kupuna-bench",
        "dataset_sha256": result.dataset_sha256,
        "rubric_version": result.rubric_version,
        "models": ", ".join(f"{m.name} ({m.family})" for m in result.models),
        "judge": f"{result.judge.name} ({result.judge.family})",
        "runs": result.runs,
        "gate": gate_name,
        "verdict": verdict,
        "shortfalls": list(shortfalls),
        "timestamp": timestamp,
        "driver": driver,
        "draft": draft or result.allow_draft,
        "metrics": metrics,
        "notes": [summary.table()],
    }


def next_record_path(records_dir: Path, day: date | None = None) -> Path:
    day = day or date.today()
    stamp = day.isoformat()
    highest = 0
    if records_dir.is_dir():
        for entry in records_dir.iterdir():
            match = _RUN_RE.match(entry.name)
            if match and match.group(1) == stamp:
                highest = max(highest, int(match.group(2)))
    return records_dir / f"run-{stamp}-{highest + 1}.md"


def _table(metrics: dict[str, Any]) -> str:
    lines = ["| metric | value |", "|---|---|"]
    for name, value in metrics.items():
        shown = f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(f"| {name} | {shown} |")
    return "\n".join(lines)


def render_record(facts: dict[str, Any], record_name: str) -> str:
    _validate(facts)
    front = [
        "---",
        f"record: {record_name}",
        f"record_version: {facts.get('record_version', RECORD_VERSION)}",
        f"system: {facts['system']}",
        f"dataset_sha256: {facts['dataset_sha256']}",
        f"rubric_version: {facts['rubric_version']}",
        f"models: {facts['models']}",
        f"judge: {facts['judge']}",
        f"runs: {facts['runs']}",
        f"gate: {facts['gate']}",
        f"verdict: {facts['verdict']}",
    ]
    if facts.get("draft"):
        front.append("draft: true")
    front += [
        f"timestamp: {facts['timestamp']}",
        f"driver: {facts['driver']}",
        f"produced_by: {facts.get('produced_by', 'worker')}",
        "---",
    ]
    draft_suffix = (
        " (DRAFT — unpromoted golden or draft scenarios)"
        if facts.get("draft")
        else ""
    )
    body = ["", f"# eval run: {facts['system']} — {facts['verdict']}{draft_suffix}", ""]
    body += ["## metrics", "", _table(facts["metrics"]), ""]
    shortfalls = cast(list[str], facts.get("shortfalls") or [])
    if shortfalls:
        body += (
            [f"## gate shortfalls ({facts['verdict']})", ""]
            + [f"- {item}" for item in shortfalls]
            + [""]
        )
    notes = cast(list[Any], facts.get("notes") or [])
    if notes:
        body += ["## notes", ""] + [str(item) for item in notes] + [""]
    return "\n".join(front + body).rstrip("\n") + "\n"


def write_record(
    facts: dict[str, Any], records_dir: Path, *, day: date | None = None, path: Path | None = None
) -> Path:
    _validate(facts)
    if path is not None:
        path = Path(path)
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(render_record(facts, path.stem))
        return path
    records_dir = Path(records_dir)
    records_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(1000):
        candidate = next_record_path(records_dir, day)
        try:
            with open(candidate, "x", encoding="utf-8") as handle:
                handle.write(render_record(facts, candidate.stem))
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(f"could not allocate a record filename in {records_dir} after 1000 attempts")
