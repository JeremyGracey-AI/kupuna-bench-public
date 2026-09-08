"""Blind label CSV templates and a transcript reading sheet, generated from a results JSON.

For each labeler, writes `<out_dir>/<labeler>-<stem>.csv`: header
`labeler,item,turn,criterion,severity,direction,note`, one row per (graded row, turn,
criterion) restricted to `run_index == 0`, with `severity` and `direction` left blank for hand
labeling. Also writes `<out_dir>/TRANSCRIPTS-<stem>.md`, one section per run-0 graded
transcript (item key, scenario title, variant, then every turn's user text and assistant
reply) with judge verdicts deliberately omitted, so a rater can label blind without opening
the results JSON.

Usage: uv run python scripts/make_label_templates.py <result.json> <labeler> [<labeler> ...]
       [--scenarios DIR] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path

from kupuna_bench.agreement import LABEL_COLUMNS, item_key
from kupuna_bench.rubric import CRITERIA
from kupuna_bench.run import Row, RunResult
from kupuna_bench.scenarios import load_scenarios


def _graded_run0(result: RunResult) -> list[Row]:
    """Rows with a judge verdict, restricted to the first run of each cell."""
    return [r for r in result.rows if r.run_index == 0 and r.verdicts is not None]


def _titles(scenarios_dir: Path) -> dict[str, str]:
    return {s.id: (s.title or s.id) for s in load_scenarios(scenarios_dir)}


def write_label_csvs(rows: Sequence[Row], labelers: Sequence[str], out_dir: Path, stem: str) -> list[Path]:
    paths: list[Path] = []
    for labeler in labelers:
        path = out_dir / f"{labeler}-{stem}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(LABEL_COLUMNS)
            for row in rows:
                assert row.verdicts is not None  # guaranteed by _graded_run0
                item = item_key(row.scenario_id, row.variant, row.model, row.run_index)
                for turn in row.verdicts.turns:
                    for criterion in CRITERIA:
                        writer.writerow([labeler, item, turn.turn, criterion, "", "", ""])
        paths.append(path)
    return paths


def write_transcript_sheet(rows: Sequence[Row], titles: dict[str, str], out_dir: Path, stem: str) -> Path:
    lines = [
        f"# Transcripts for blind labeling — {stem}",
        "",
        f"{len(rows)} run-0, graded transcripts (rows with a chat or judge error are excluded: "
        "there is nothing to label). Judge verdicts and rationales are deliberately omitted "
        "below; label from the conversation text only.",
        "",
    ]
    for row in rows:
        item = item_key(row.scenario_id, row.variant, row.model, row.run_index)
        lines += [
            f"## {item}",
            "",
            f"scenario: {titles.get(row.scenario_id, row.scenario_id)}  ",
            f"variant: {row.variant}  ",
            f"model: {row.model}  tier: {row.tier}  domain: {row.domain}",
            "",
        ]
        for index, exchange in enumerate(row.transcript.exchanges):
            lines.append(f"**turn {index} — user:** {exchange.user}")
            lines.append("")
            lines.append(f"**turn {index} — assistant:** {exchange.assistant}")
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
) -> tuple[list[Path], Path]:
    result = RunResult.model_validate(json.loads(Path(result_json).read_text(encoding="utf-8")))
    rows = _graded_run0(result)
    titles = _titles(Path(scenarios_dir))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result_json).stem
    csv_paths = write_label_csvs(rows, labelers, out_dir, stem)
    sheet_path = write_transcript_sheet(rows, titles, out_dir, stem)
    return csv_paths, sheet_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate blind label templates from a results JSON.")
    parser.add_argument("result_json", type=Path)
    parser.add_argument("labelers", nargs="+", help="Labeler names, e.g. melissa jeremy")
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios/probe"), dest="scenarios_dir")
    parser.add_argument("--out-dir", type=Path, default=Path("labels"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    written_csvs, written_sheet = main(
        args.result_json, args.labelers, scenarios_dir=args.scenarios_dir, out_dir=args.out_dir
    )
    for csv_path in written_csvs:
        print(csv_path)
    print(written_sheet)
