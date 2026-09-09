"""Blind label templates from a results JSON (review finding 4).

Each labeler gets `<out_dir>/<labeler>-<stem>.csv` (columns `labeler,item,turn,criterion,severity,
direction,note`, `severity` and `direction` blank) and everyone shares
`<out_dir>/TRANSCRIPTS-<stem>.md`. Items carry opaque ids (`item-01`, ...): the sheet shows the
scenario title, domain, tier, every turn's user text and reply, and by default that turn's answer key;
never the model, the condition name, the run index, or a judge verdict. Presentation order is
shuffled by seed. Selection takes `--runs-per-cell` run indices per (scenario, variant, model) by seed
and adds every complete transcript whose judge call failed, because those are the ones a human label
can check the grader against. The decoding map `{opaque id: scenario|variant|model|run}` is written to
`--key-out` (default: next to the results JSON, never under labels/); `kupuna-bench agreement --key`
reads it.

Usage: uv run python scripts/make_label_templates.py <result.json> <labeler> [<labeler> ...]
       [--scenarios DIR] [--out-dir DIR] [--key-out FILE] [--runs-per-cell N] [--seed N] [--no-keys]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Sequence
from pathlib import Path

from kupuna_bench.agreement import LABEL_COLUMNS, item_key
from kupuna_bench.rubric import CRITERIA
from kupuna_bench.run import Row, RunResult
from kupuna_bench.scenarios import AnswerKey, Scenario, load_scenarios


def _key(row: Row) -> str:
    return item_key(row.scenario_id, row.variant, row.model, row.run_index)


def eligible(result: RunResult) -> list[Row]:
    """Complete transcripts: graded rows, and rows whose only failure was the judge."""
    complete = [r for r in result.rows if r.transcript.exchanges]
    return [r for r in complete if r.error is None or r.error.stage == "judge"]


def select(rows: Sequence[Row], *, runs_per_cell: int = 1, seed: int = 0) -> list[Row]:
    """`runs_per_cell` run indices per (scenario, variant, model) by seed, plus every judge-error row."""
    cells: dict[tuple[str, str, str], list[Row]] = {}
    for row in rows:
        cells.setdefault((row.scenario_id, row.variant, row.model), []).append(row)
    rng = random.Random(seed)
    chosen: list[Row] = []
    for cell in sorted(cells):
        members = sorted(cells[cell], key=lambda r: r.run_index)
        chosen.extend(rng.sample(members, min(runs_per_cell, len(members))))
    seen = {_key(r) for r in chosen}
    for row in rows:
        if row.error is not None and _key(row) not in seen:
            chosen.append(row)
            seen.add(_key(row))
    return chosen


def presentation(rows: Sequence[Row], *, seed: int = 0) -> list[tuple[str, Row]]:
    """Shuffled order with opaque ids; the map back to full keys is the caller's to keep apart."""
    order = list(rows)
    random.Random(f"{seed}:order").shuffle(order)
    width = max(2, len(str(len(order))))
    return [(f"item-{index + 1:0{width}d}", row) for index, row in enumerate(order)]


def write_label_csvs(
    items: Sequence[tuple[str, Row]], labelers: Sequence[str], out_dir: Path, stem: str
) -> list[Path]:
    paths: list[Path] = []
    for labeler in labelers:
        path = out_dir / f"{labeler}-{stem}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(LABEL_COLUMNS)
            for opaque, row in items:
                for turn in range(row.transcript.turns):
                    for criterion in CRITERIA:
                        writer.writerow([labeler, opaque, turn, criterion, "", "", ""])
        paths.append(path)
    return paths


def _key_lines(key: AnswerKey) -> list[str]:
    lines = [f"expected: {key.expected.strip()}"]
    if key.warranted_warnings:
        lines.append("warranted warnings: " + "; ".join(key.warranted_warnings))
    if key.unwarranted_warnings:
        lines.append("unwarranted warnings: " + "; ".join(key.unwarranted_warnings))
    lines.append(f"referral: {key.referral}")
    return lines


def write_transcript_sheet(
    items: Sequence[tuple[str, Row]],
    scenarios: dict[str, Scenario],
    out_dir: Path,
    stem: str,
    *,
    with_keys: bool = True,
) -> Path:
    lines = [
        f"# Transcripts for blind labeling: {stem}",
        "",
        f"{len(items)} conversations in shuffled order. The model, the condition, and the repetition are "
        "hidden; judge verdicts and rationales are omitted. Label each reply from the conversation text"
        + (" and the answer key shown for that turn." if with_keys else "."),
        "",
    ]
    for opaque, row in items:
        scenario = scenarios.get(row.scenario_id)
        title = (scenario.title or scenario.id) if scenario else row.scenario_id
        lines += [f"## {opaque}", "", f"scenario: {title}  ", f"domain: {row.domain}  tier: {row.tier}", ""]
        for index, exchange in enumerate(row.transcript.exchanges):
            lines += [f"**turn {index}, user:** {exchange.user}", ""]
            lines += [f"**turn {index}, assistant:** {exchange.assistant}", ""]
            if with_keys and scenario is not None:
                lines.append(f"**turn {index}, answer key:**")
                lines += [f"- {line}" for line in _key_lines(scenario.key_for(index))]
                lines.append("")
        lines += ["---", ""]
    path = out_dir / f"TRANSCRIPTS-{stem}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(
    result_json: Path,
    labelers: Sequence[str],
    *,
    scenarios_dir: Path = Path("scenarios/probe"),
    out_dir: Path = Path("labels"),
    key_out: Path | None = None,
    runs_per_cell: int = 1,
    seed: int = 0,
    with_keys: bool = True,
) -> tuple[list[Path], Path, Path]:
    result_json = Path(result_json)
    result = RunResult.model_validate(json.loads(result_json.read_text(encoding="utf-8")))
    items = presentation(select(eligible(result), runs_per_cell=runs_per_cell, seed=seed), seed=seed)
    scenarios = {s.id: s for s in load_scenarios(Path(scenarios_dir))}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = result_json.stem
    csv_paths = write_label_csvs(items, labelers, out_dir, stem)
    sheet_path = write_transcript_sheet(items, scenarios, out_dir, stem, with_keys=with_keys)
    key_path = Path(key_out) if key_out is not None else result_json.parent / f"KEY-{stem}.json"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_map = {opaque: _key(row) for opaque, row in items}
    key_path.write_text(json.dumps(key_map, indent=1) + "\n", encoding="utf-8")
    return csv_paths, sheet_path, key_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate blind label templates from a results JSON.")
    parser.add_argument("result_json", type=Path)
    parser.add_argument("labelers", nargs="+", help="Labeler names, e.g. melissa jeremy")
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios/probe"), dest="scenarios_dir")
    parser.add_argument("--out-dir", type=Path, default=Path("labels"))
    parser.add_argument("--key-out", type=Path, default=None, help="Decoding map (default: next to the JSON)")
    parser.add_argument("--runs-per-cell", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-keys", action="store_true", help="Leave the answer keys out of the sheet")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    written_csvs, written_sheet, written_key = main(
        args.result_json,
        args.labelers,
        scenarios_dir=args.scenarios_dir,
        out_dir=args.out_dir,
        key_out=args.key_out,
        runs_per_cell=args.runs_per_cell,
        seed=args.seed,
        with_keys=not args.no_keys,
    )
    for csv_path in written_csvs:
        print(csv_path)
    print(written_sheet)
    print(f"key map (keep apart from the sheets): {written_key}")
